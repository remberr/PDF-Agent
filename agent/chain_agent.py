def plan_steps(question):
    """
    Plan multiple tool steps according to the user's request.
    """

    question_lower = question.lower()

    steps = []

    if (
        "compare" in question_lower
        or "comparison" in question_lower
        or "比较" in question
        or "对比" in question
        or "比較" in question
    ):
        steps.append("compare")

    if (
        "summary" in question_lower
        or "summarize" in question_lower
        or "总结" in question
        or "概括" in question
        or "要約" in question
    ):
        steps.append("summary")

    if (
        "keyword" in question_lower
        or "keywords" in question_lower
        or "关键词" in question
        or "キーワード" in question
    ):
        steps.append("keyword")

    if (
        "source" in question_lower
        or "page" in question_lower
        or "来源" in question
        or "出处" in question
        or "页码" in question
        or "ページ" in question
    ):
        steps.append("source")

    if not steps:
        steps.append("qa")

    return steps