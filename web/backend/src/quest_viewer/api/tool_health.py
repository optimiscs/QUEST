"""Classify recorded tool envelopes, never search-result/page prose."""

import json
import math
import re


def payload(raw):
    if isinstance(raw, dict):
        return raw
    raw = str(raw or "").strip()
    if raw.startswith("<untrusted_tool_result"):
        end = raw.rfind("</untrusted_tool_result>")
        if end >= 0:
            raw = raw[:end]
        # The wrapper includes an instruction paragraph before the JSON body.
        for match in re.finditer(r"(?m)^\s*(?=[{\[])", raw):
            try:
                return json.loads(raw[match.end() :].strip())
            except ValueError:
                continue
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def category(message):
    text = message.lower()
    patterns = [
        (
            "限流 / 队列拥塞",
            r"\b429\b|rate.?limit|too many requests|queue.?full|queue.?timeout|queue.*wait|overload",
        ),
        ("额度耗尽", r"quota|credit.*exhaust|insufficient.*credit|payment required|\b402\b"),
        ("密钥 / 鉴权", r"\b401\b|unauthori|invalid.*key|api.?key.*invalid|authentication"),
        ("DNS 解析", r"dns|name resolution|name or service not known|getaddrinfo"),
        (
            "安全校验 / 私网拦截",
            r"private.*(address|network)|internal.*(address|network)|url.*blocked|blocked.*url|ssrf",
        ),
        ("超时", r"timeout|timed? out|time.?budget|deadline|超时"),
        (
            "工具不存在 / 参数错误",
            r"does not exist|unknown tool|invalid.*(name|argument|parameter)|validation error|\b400\b|\b422\b",
        ),
        ("网络 / 连接", r"connection|connect error|network|ssl|tls|certificate|remoteprotocol"),
        ("网页拒绝 / 不存在", r"\b403\b|\b404\b|forbidden|not found|captcha|robots"),
        ("上游服务错误", r"\b5\d\d\b|bad gateway|service unavailable|internal server"),
        ("执行错误", r"traceback|exception|exited [1-9]|exit code|execution error"),
        ("中断 / 取消", r"interrupt|cancel|abort"),
    ]
    return next((label for label, pattern in patterns if re.search(pattern, text)), "其他工具错误")


def error_of(obj):
    if not isinstance(obj, dict):
        return ""
    if obj.get("error"):
        value = obj["error"]
        return (
            str(obj.get("error_code") or obj.get("code") or "")
            + " "
            + (json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value))
        ).strip()
    if obj.get("success") is False or str(obj.get("status", "")).lower() in ("error", "failed", "failure"):
        return (
            str(obj.get("error_code") or "")
            + " "
            + str(obj.get("message") or obj.get("status") or "success=false")
        )
    return ""


def classify(step, in_progress=False):
    tool = step.get("tool") or {}
    raw = step.get("rawToolOutput")
    if raw is None:
        raw = tool.get("stdout", "")
    obj = payload(raw)
    if isinstance(obj, dict) and obj.get("status") == "tool_budget_denied":
        return dict(status="excluded", reasons=[], error="工具预算耗尽，未执行", zeroResults=False)
    if isinstance(raw, str) and raw.startswith("Skipped:"):
        return dict(status="excluded", reasons=[], error=raw[:2000], zeroResults=False)
    errors = []
    top = error_of(obj) or str(tool.get("error") or "")
    if top:
        errors.append(top)
    children = obj.get("results") if isinstance(obj, dict) else None
    if isinstance(children, list):
        errors.extend(e for child in children if (e := error_of(child)))
    # Historical adapters hid errors behind count=0 or a page summary. These
    # are explicit failure prefixes; ordinary retrieved text is never scanned.
    if not errors:
        for page in tool.get("pages", []):
            summary = str(page.get("summary") or "")
            if summary.startswith("读取失败："):
                errors.append(summary[len("读取失败：") :])
        for query in tool.get("queries", []):
            if query.get("error"):
                errors.append(str(query["error"]))
    if (
        not errors
        and isinstance(raw, str)
        and re.match(
            r"^(Error\b|Tool '[^']+' does not exist|search_server failed|搜索失败[:：])", raw.strip(), re.I
        )
    ):
        errors.append(raw.strip())
    if errors:
        partial = (
            isinstance(children, list)
            and 0 < sum(bool(error_of(x)) for x in children) < len(children)
            and not top
        )
        return dict(
            status="failed",
            reasons=sorted({category(e) for e in errors}),
            error="\n".join(dict.fromkeys(errors))[:4000],
            partial=partial,
            zeroResults=False,
        )
    if not raw:
        return dict(status="pending" if in_progress else "unknown", reasons=[], error="", zeroResults=False)
    success = False
    results = None
    if isinstance(obj, dict):
        status = str(obj.get("status", "")).lower()
        success = obj.get("success") is True or status in ("success", "ok", "completed")
        if isinstance(children, list) and children:
            # An extraction/delegation envelope without per-item errors.
            success |= all(
                isinstance(c, dict) and (c.get("status") == "completed" or "content" in c) for c in children
            )
        data = obj.get("data")
        if isinstance(data, dict) and isinstance(data.get("web"), list):
            results = data["web"]
        elif isinstance(obj.get("organic"), list):
            results = obj["organic"]
        elif isinstance(children, list) and step.get("kind") == "search":
            results = children
        # A recognized search-result envelope is affirmative evidence, unlike
        # the viewer's old count=0 default. Explicit errors already won above.
        if step.get("kind") == "search" and results is not None:
            success = True
    return dict(
        status="success" if success else "unknown",
        reasons=[],
        error="",
        zeroResults=bool(success and step.get("kind") == "search" and results == []),
    )


def tool_events(body):
    events = []
    seen = set()
    for step in body.get("steps", []):
        if not step.get("tool") and not step.get("toolCallId"):
            continue
        key = (step.get("sourceSessionId"), step.get("toolCallId"))
        if key[1] and key in seen:
            continue
        if key[1]:
            seen.add(key)
        result = classify(step, body.get("inProgress", False))
        end = step.get("toolEnd")
        if not isinstance(end, (int, float)) or not math.isfinite(end) or end < 0:
            end = None
        tool = step.get("tool") or {}
        events.append(
            dict(
                result,
                step=step.get("n"),
                tool=tool.get("name") or "未执行工具",
                elapsedSeconds=end,
                durationSeconds=step.get("tool_seconds"),
                queries=[str(q.get("query") or "") for q in tool.get("queries", [])],
            )
        )
    return events
