"""Local PDF corpus, verifiable references and production FAISS retrieval.

No reference annotations are passed to the index or workflow. Only the chosen
corpus filenames (the equivalent of uploaded PDFs) constrain retrieval.
"""
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from time import perf_counter

from app.services.pdf_service import parse_pdf_documents
from utils.text_splitter import split_documents
from utils.vectorstore import EMBEDDING_MODEL, create_vectorstore


DEFAULT_REAL_DATASET = Path(__file__).with_name('real_pdf_cases.json')
DEFAULT_MANIFEST = Path(__file__).with_name('pdf_manifest.json')


def normalize_evidence(text):
    text = unicodedata.normalize('NFKC', text)
    text = re.sub(r'-\s*\n\s*', '', text)
    return ' '.join(text.split())


def validate_real_cases(cases, filenames):
    seen = set()
    for case in cases:
        if case['id'] in seen:
            raise ValueError(f"Duplicate case ID: {case['id']}")
        seen.add(case['id'])
        if not case.get('pdf_files') or not set(case['pdf_files']) <= set(filenames):
            raise ValueError(f"Invalid corpus scope: {case['id']}")
        for field in ('required_facts', 'expected_citations', 'forbidden_claims'):
            if not isinstance(case.get(field), list):
                raise ValueError(f"Missing annotation {field}: {case['id']}")
        if not case.get('required_facts') or not case.get('expected_behavior'):
            raise ValueError(f"Missing facts/behavior: {case['id']}")
        if case.get('answerability') not in ('answerable', 'unanswerable', 'insufficient_evidence'):
            raise ValueError(f"Invalid answerability: {case['id']}")
        if case.get('annotation', {}).get('status') not in ('pending_human_review', 'human_verified'):
            raise ValueError(f"Annotation review status required: {case['id']}")
        citations = set()
        for citation in case['expected_citations']:
            if citation['source'] not in case['pdf_files'] or type(citation['page']) is not int or citation['page'] < 1 or not citation.get('evidence'):
                raise ValueError(f"Invalid reference citation: {case['id']}")
            citations.add(f"{citation['source']}, page {citation['page']}")
        ids = set()
        for fact in case['required_facts']:
            if not fact.get('id') or fact['id'] in ids or not fact.get('statement'):
                raise ValueError(f"Invalid required fact: {case['id']}")
            ids.add(fact['id'])
            if not set(fact.get('citations', [])) <= citations:
                raise ValueError(f"Fact refers to unknown citation: {case['id']}")
            if case['answerability'] == 'answerable' and not fact.get('citations'):
                raise ValueError(f"Answerable fact lacks evidence: {case['id']}")


class RealPDFCorpus:
    def __init__(self, pdf_dir, manifest_path=DEFAULT_MANIFEST):
        started = perf_counter()
        self.pages = {}
        self.chunks = {}
        self.indexes = {}
        self.manifest = []
        self.index_build_ms = 0.0
        manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
        for item in manifest['files']:
            name = item['filename']
            if Path(name).name != name:
                raise ValueError('Manifest filenames must be basenames.')
            path = Path(pdf_dir) / name
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != item['sha256']:
                raise ValueError(f'PDF SHA-256 mismatch: {name}. Review the PDF version and annotations.')
            pages = parse_pdf_documents(path, name)
            if len(pages) != item['pages']:
                raise ValueError(f'PDF page count mismatch: {name}')
            self.pages[name] = pages
            self.chunks[name] = split_documents(pages)
            self.manifest.append(item | {'chunk_count': len(self.chunks[name])})
        self.parse_ms = round((perf_counter() - started) * 1000, 2)

    def validate_evidence(self, cases):
        validate_real_cases(cases, self.pages)
        checked = 0
        for case in cases:
            for citation in case['expected_citations']:
                pages = self.pages[citation['source']]
                page_number = citation['page']
                if page_number > len(pages):
                    raise ValueError(f"Reference page out of range: {case['id']}")
                text = normalize_evidence(pages[page_number - 1].page_content)
                for quote in citation['evidence']:
                    if not normalize_evidence(quote) or normalize_evidence(quote) not in text:
                        raise ValueError(f"Evidence quote missing: {case['id']}, {citation['source']}, page {page_number}: {quote}")
                    checked += 1
        return {'case_count': len(cases), 'evidence_quotes_checked': checked,
                'annotation_status': 'provisional' if any(c['annotation']['status'] != 'human_verified' for c in cases) else 'human_verified',
                'semantic_ground_truth_verified': all(c['annotation']['status'] == 'human_verified' for c in cases),
                'note': 'Hash/page/quote matching validates provenance, not semantic correctness or absence claims. Human review is still required.'}

    def vectorstore_for(self, filenames):
        key = tuple(sorted(filenames))
        if key not in self.indexes:
            started = perf_counter()
            chunks = [doc for name in key for doc in self.chunks[name]]
            self.indexes[key] = create_vectorstore(chunks)
            self.index_build_ms += (perf_counter() - started) * 1000
        return self.indexes[key]

    def metadata(self):
        return {'files': self.manifest, 'embedding_model': EMBEDDING_MODEL,
                'parse_ms': self.parse_ms, 'index_build_ms': round(self.index_build_ms, 2),
                'index_scope_count': len(self.indexes),
                'splitter': {'chunk_size': 1200, 'chunk_overlap': 250},
                'reference_evidence_in_agent_context': False}
