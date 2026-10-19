import type { Language } from "./types";

export interface Translation {
  brandSubtitle: string;
  languageLabel: string;
  api: {
    online: string;
    offline: string;
    connecting: string;
  };
  session: {
    label: string;
    copied: string;
    copy: string;
    new: string;
    confirmNew: string;
  };
  nav: {
    label: string;
    documents: string;
    analysis: string;
    workflow: string;
  };
  documents: {
    library: string;
    title: string;
    countLabel: string;
    indexing: string;
    add: string;
    drop: string;
    indexed: string;
    ready: string;
    empty: string;
    pagesIndexed: string;
  };
  chat: {
    workspace: string;
    title: string;
    grounded: string;
    start: string;
    suggestions: string[];
    you: string;
    agent: string;
    running: string;
    sources: string;
    page: string;
    askPlaceholder: string;
    addPdfPlaceholder: string;
    send: string;
  };
  workflow: {
    trace: string;
    title: string;
    planner: string;
    routeSelected: string;
    waiting: string;
    specialists: string;
    collaboration: string;
    controller: string;
    revision: string;
    retry: string;
    reviewer: string;
    answerDelivered: string;
    agents: string;
    sources: string;
    retries: string;
    issues: string;
    missingInformation: string;
    recommendations: string;
    requestedSteps: string;
    runtime: string;
    total: string;
    usage: string;
    calls: string;
    tokens: string;
    cacheHit: string;
    cacheUnavailable: string;
    noLlmCalls: string;
    estimatedCost: string;
    operations: string;
    unavailable: string;
    usageOperations: Record<string, string>;
    steps: Record<string, string>;
    statuses: Record<string, string>;
  };
  errors: {
    apiUnavailable: string;
    createSession: string;
    uploadFailed: string;
    analysisFailed: string;
    pdfOnly: string;
    addPdfFirst: string;
  };
}

export const translations: Record<Language, Translation> = {
  en: {
    brandSubtitle: "Multi-agent research workspace",
    languageLabel: "Language",
    api: {
      online: "API online",
      offline: "API offline",
      connecting: "Connecting",
    },
    session: {
      label: "Session",
      copied: "Copied",
      copy: "Copy session ID",
      new: "New session",
      confirmNew: "Start a new PDF session?",
    },
    nav: {
      label: "Workspace views",
      documents: "Documents",
      analysis: "Analysis",
      workflow: "Workflow",
    },
    documents: {
      library: "Library",
      title: "Documents",
      countLabel: "documents",
      indexing: "Indexing PDFs",
      add: "Add PDFs",
      drop: "Drop files here or browse",
      indexed: "Indexed",
      ready: "Ready",
      empty: "No PDFs in this session",
      pagesIndexed: "Pages indexed",
    },
    chat: {
      workspace: "Workspace",
      title: "PDF analysis",
      grounded: "RAG grounded",
      start: "Start an analysis",
      suggestions: [
        "Summarize the uploaded documents.",
        "Compare the main findings and cite sources.",
        "Extract the most important concepts.",
      ],
      you: "You",
      agent: "PDF Agent",
      running: "Running agent workflow",
      sources: "Sources",
      page: "Page",
      askPlaceholder: "Ask about your PDFs",
      addPdfPlaceholder: "Add a PDF to begin",
      send: "Send question",
    },
    workflow: {
      trace: "Trace",
      title: "Workflow",
      planner: "Planner Agent",
      routeSelected: "Route selected",
      waiting: "Waiting",
      specialists: "Specialist Agents",
      collaboration: "Collaboration Agent",
      controller: "Workflow Controller",
      revision: "Revision Controller",
      retry: "retry",
      reviewer: "Reviewer Agent",
      answerDelivered: "Answer delivered",
      agents: "Agents",
      sources: "Sources",
      retries: "Retries",
      issues: "Issues",
      missingInformation: "Missing information",
      recommendations: "Recommendations",
      requestedSteps: "Requested steps",
      runtime: "Runtime",
      total: "Total",
      usage: "LLM usage",
      calls: "Calls",
      tokens: "Tokens",
      cacheHit: "Cache hit",
      cacheUnavailable: "Stats unavailable",
      noLlmCalls: "No LLM calls",
      estimatedCost: "Est. cost (USD)",
      operations: "Usage by operation",
      unavailable: "Unavailable",
      usageOperations: {
        planner: "Planner",
        qa: "QA",
        source: "Source",
        summary: "Summary",
        keyword: "Keywords",
        compare: "Comparison",
        collaboration: "Collaboration",
        reviewer: "Reviewer",
        memory_summary: "Memory summary",
        evaluation_judge: "Evaluation judge",
      },
      steps: {
        qa: "QA Agent",
        source: "Source Agent",
        summary: "Summary Agent",
        keyword: "Keyword Agent",
        compare: "Compare Agent",
      },
      statuses: {
        success: "Success",
        failed: "Failed",
        skipped: "Skipped",
        waiting: "Waiting",
        running: "Running",
        completed: "Completed",
      },
    },
    errors: {
      apiUnavailable: "Cannot reach the PDF Agent API.",
      createSession: "Could not create a session.",
      uploadFailed: "PDF upload failed.",
      analysisFailed: "The analysis failed.",
      pdfOnly: "Only PDF files are supported.",
      addPdfFirst: "Please upload at least one PDF first.",
    },
  },
  zh: {
    brandSubtitle: "多智能体文档研究工作台",
    languageLabel: "语言",
    api: {
      online: "API 在线",
      offline: "API 离线",
      connecting: "连接中",
    },
    session: {
      label: "会话",
      copied: "已复制",
      copy: "复制会话 ID",
      new: "新建会话",
      confirmNew: "确定要新建 PDF 会话吗？",
    },
    nav: {
      label: "工作区视图",
      documents: "文档",
      analysis: "分析",
      workflow: "工作流",
    },
    documents: {
      library: "资料库",
      title: "文档",
      countLabel: "份文档",
      indexing: "正在建立索引",
      add: "添加 PDF",
      drop: "拖放文件或点击选择",
      indexed: "已建立索引",
      ready: "就绪",
      empty: "当前会话还没有 PDF",
      pagesIndexed: "已索引页数",
    },
    chat: {
      workspace: "工作台",
      title: "PDF 分析",
      grounded: "基于 RAG",
      start: "开始分析",
      suggestions: [
        "总结已上传的文档。",
        "比较主要结论并标注来源。",
        "提取最重要的概念。",
      ],
      you: "你",
      agent: "PDF Agent",
      running: "Agent 工作流运行中",
      sources: "参考来源",
      page: "页码",
      askPlaceholder: "针对 PDF 提问",
      addPdfPlaceholder: "添加 PDF 后开始提问",
      send: "发送问题",
    },
    workflow: {
      trace: "执行轨迹",
      title: "工作流",
      planner: "规划 Agent",
      routeSelected: "已选择执行路线",
      waiting: "等待中",
      specialists: "专业 Agent",
      collaboration: "协作 Agent",
      controller: "工作流控制器",
      revision: "修订控制器",
      retry: "次重试",
      reviewer: "审查 Agent",
      answerDelivered: "已生成答案",
      agents: "Agent 数",
      sources: "来源数",
      retries: "重试数",
      issues: "发现的问题",
      missingInformation: "缺失信息",
      recommendations: "改进建议",
      requestedSteps: "追加步骤",
      runtime: "运行耗时",
      total: "总耗时",
      usage: "LLM 用量",
      calls: "调用数",
      tokens: "Token",
      cacheHit: "缓存命中",
      cacheUnavailable: "统计不可用",
      noLlmCalls: "无 LLM 调用",
      estimatedCost: "预估费用（元）",
      operations: "按操作拆分",
      unavailable: "不可估算",
      usageOperations: {
        planner: "规划",
        qa: "问答",
        source: "来源",
        summary: "总结",
        keyword: "关键词",
        compare: "对比",
        collaboration: "协作",
        reviewer: "审查",
        memory_summary: "记忆摘要",
        evaluation_judge: "评测 Judge",
      },
      steps: {
        qa: "问答 Agent",
        source: "来源 Agent",
        summary: "总结 Agent",
        keyword: "关键词 Agent",
        compare: "对比 Agent",
      },
      statuses: {
        success: "成功",
        failed: "失败",
        skipped: "已跳过",
        waiting: "等待中",
        running: "运行中",
        completed: "已完成",
      },
    },
    errors: {
      apiUnavailable: "无法连接 PDF Agent API。",
      createSession: "无法创建会话。",
      uploadFailed: "PDF 上传失败。",
      analysisFailed: "分析失败。",
      pdfOnly: "仅支持 PDF 文件。",
      addPdfFirst: "请先上传至少一份 PDF。",
    },
  },
};
