def route_question(question):
    """
    Route the user's question to the appropriate tool.

    Supported task types:
    - compare: Compare multiple PDFs
    - summary: Summarize uploaded PDFs
    - keyword: Extract keywords from PDFs
    - source: Find related sources or pages
    - qa: Normal PDF question answering
    """

    # Convert English text to lowercase
    # for easier keyword matching
    question_lower = question.lower()

    # Compare Tool:
    # Used when the user wants to compare PDFs
    if (
        "compare" in question_lower
        or "comparison" in question_lower
        or "区别" in question
        or "比较" in question
        or "对比" in question
        or "違い" in question
        or "比較" in question
    ):
        return "compare"

    # Summary Tool:
    # Used when the user wants a summary
    if (
        "summary" in question_lower
        or "summarize" in question_lower
        or "summarise" in question_lower
        or "总结" in question
        or "概括" in question
        or "要約" in question
        or "まとめ" in question
    ):
        return "summary"

    # Keyword Tool:
    # Used when the user wants keywords
    if (
        "keyword" in question_lower
        or "keywords" in question_lower
        or "key concepts" in question_lower
        or "关键词" in question
        or "关键概念" in question
        or "キーワード" in question
        or "重要語" in question
    ):
        return "keyword"

    # Source Tool:
    # Used when the user wants source pages or evidence
    if (
        "source" in question_lower
        or "sources" in question_lower
        or "page" in question_lower
        or "pages" in question_lower
        or "reference" in question_lower
        or "citation" in question_lower
        or "来源" in question
        or "出处" in question
        or "页码" in question
        or "ページ" in question
        or "出典" in question
    ):
        return "source"

    # Default Tool:
    # Used for normal question answering
    return "qa"