"""HTML email template for Guide Agent plan emails — single bug class focused."""

from __future__ import annotations

import html

from guide_agent.models import Plan, Task

PRIORITY_COLOR = {
    "critical": "#ef4444",
    "high": "#f97316",
    "medium": "#3b82f6",
    "low": "#6b7280",
}


def render_plan_email(plan: Plan) -> str:
    """Render a Plan as a dark-themed responsive HTML email."""
    phase_label = plan.phase.value.upper()
    mode_label = (
        f" — {plan.research_mode.value.replace('_', ' ').title()}"
        if plan.research_mode is not None else ""
    )

    tasks_html = "".join(_render_task(i, t) for i, t in enumerate(plan.tasks, 1))

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Guide — {html.escape(plan.bug_class_name)}</title>
</head>
<body style="margin:0;padding:0;background-color:#0a0a0f;color:#e5e7eb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;line-height:1.6;">

<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#0a0a0f;padding:40px 20px;">
  <tr><td align="center">
    <table width="640" cellpadding="0" cellspacing="0" border="0" style="max-width:640px;">

      <!-- HEADER -->
      <tr><td style="padding:0 0 24px 0;">
        <p style="margin:0;font-size:11px;font-weight:700;color:#10b981;text-transform:uppercase;letter-spacing:2px;">
          Guide · {html.escape(plan.date)}
        </p>
        <h1 style="margin:8px 0 4px 0;font-size:28px;font-weight:700;color:#f9fafb;">
          {html.escape(plan.bug_class_name)}
        </h1>
        <p style="margin:0;font-size:14px;color:rgba(255,255,255,0.55);">
          {html.escape(phase_label)} phase{html.escape(mode_label)} · {plan.target_hours}h target
        </p>
      </td></tr>

      {_rationale_block(plan.rationale)}

      <!-- TASKS -->
      <tr><td style="padding:8px 0 0 0;">
        <p style="margin:0 0 12px 0;font-size:10px;font-weight:700;color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:1.5px;">
          Today's Tasks ({len(plan.tasks)})
        </p>
        {tasks_html}
      </td></tr>

      {_tools_section_block(plan)}

      <!-- HOW TO REPLY -->
      <tr><td style="padding:32px 0 0 0;">
        <p style="margin:0 0 8px 0;font-size:10px;font-weight:700;color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:1.5px;">
          How to reply
        </p>
        <p style="margin:0;font-size:13px;color:rgba(255,255,255,0.55);line-height:1.7;">
          Reply with task updates in this format:<br>
          <code style="background:#1a1a24;padding:2px 6px;border-radius:4px;color:#10b981;">1: done 2.5h — learned X</code><br>
          <code style="background:#1a1a24;padding:2px 6px;border-radius:4px;color:#10b981;">2: skip — too easy, want harder</code><br>
          Or any free-form thoughts at the end — they'll be saved as user notes.
        </p>
      </td></tr>

      <!-- FOOTER -->
      <tr><td style="padding:32px 0 0 0;border-top:1px solid rgba(255,255,255,0.08);">
        <p style="margin:24px 0 0 0;font-size:11px;color:rgba(255,255,255,0.3);text-align:center;">
          Guide Agent · bug-class mastery, on demand
        </p>
      </td></tr>

    </table>
  </td></tr>
</table>

</body>
</html>"""


def _rationale_block(rationale: str) -> str:
    if not rationale.strip():
        return ""
    return f"""
      <tr><td style="padding:0 0 24px 0;">
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:rgba(16,185,129,0.06);border-radius:8px;border:1px solid rgba(16,185,129,0.12);">
          <tr><td style="padding:14px 18px;">
            <p style="margin:0 0 6px 0;font-size:10px;font-weight:700;color:#10b981;text-transform:uppercase;letter-spacing:1.5px;">
              Why this plan
            </p>
            <p style="margin:0;font-size:13px;color:rgba(255,255,255,0.75);line-height:1.6;">
              {html.escape(rationale)}
            </p>
          </td></tr>
        </table>
      </td></tr>
    """


def _tools_section_block(plan: Plan) -> str:
    """Render the tools_section block (execute phase only). Empty → no block."""
    if not plan.tools_section:
        return ""
    items = "".join(_render_tool_item(t) for t in plan.tools_section)
    return f"""
      <tr><td style="padding:32px 0 0 0;">
        <p style="margin:0 0 10px 0;font-size:10px;font-weight:700;color:#10b981;text-transform:uppercase;letter-spacing:1.5px;">
          Tools for Hunting ({len(plan.tools_section)})
        </p>
        <p style="margin:0 0 12px 0;font-size:12px;color:rgba(255,255,255,0.5);line-height:1.5;">
          Openly-available tools you can download and use. Pick whichever fits the target you chose above.
        </p>
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:rgba(16,185,129,0.05);border-radius:10px;border:1px solid rgba(16,185,129,0.15);">
          <tr><td style="padding:14px 18px;">
            <table width="100%" cellpadding="0" cellspacing="0" border="0">
              {items}
            </table>
          </td></tr>
        </table>
      </td></tr>
    """


def _render_tool_item(tool) -> str:  # type: ignore[no-untyped-def]
    """One tool row inside the tools_section block."""
    name = tool.name or tool.url
    if len(name) > 90:
        name = name[:87] + "..."
    note_html = ""
    if tool.note:
        note_html = (
            f'<p style="margin:2px 0 0 0;font-size:12px;color:rgba(255,255,255,0.5);line-height:1.5;">'
            f'{html.escape(tool.note)}</p>'
        )
    return f"""
        <tr><td style="padding:5px 0;">
          <a href="{html.escape(tool.url)}" style="color:#34d399;text-decoration:none;font-size:13px;font-weight:600;">
            {html.escape(name)}
          </a>
          {note_html}
          <p style="margin:1px 0 0 0;font-size:10px;color:rgba(255,255,255,0.25);word-break:break-all;">
            {html.escape(tool.url)}
          </p>
        </td></tr>
    """


def _render_task(idx: int, task: Task) -> str:
    color = PRIORITY_COLOR.get(task.priority.value, "#6b7280")

    # Anchor block — the primary resource URL (always shown if present)
    url_block = ""
    if task.primary_resource_url:
        name = task.primary_resource_name or task.primary_resource_url
        if len(name) > 80:
            name = name[:77] + "..."
        url_block = f"""
            <tr><td style="padding:10px 0 0 0;">
              <a href="{html.escape(task.primary_resource_url)}" style="color:#60a5fa;text-decoration:none;font-size:13px;font-weight:600;">
                → {html.escape(name)}
              </a>
              <p style="margin:2px 0 0 0;font-size:11px;color:rgba(255,255,255,0.3);word-break:break-all;">
                {html.escape(task.primary_resource_url)}
              </p>
            </td></tr>
        """

    # Resources list — render every URL in the bundle as a clickable list.
    # If the primary URL is also the first resource, that's expected —
    # the anchor at the top is for quick navigation, the resources list is
    # the actionable "what to read" list.
    resources_block = ""
    if task.resources:
        items = "".join(_render_resource_item(r) for r in task.resources)
        resources_block = f"""
            <tr><td style="padding:14px 0 0 0;">
              <p style="margin:0 0 6px 0;font-size:10px;font-weight:700;color:rgba(255,255,255,0.35);text-transform:uppercase;letter-spacing:1.2px;">
                Resources ({len(task.resources)})
              </p>
              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                {items}
              </table>
            </td></tr>
        """

    why_block = ""
    if task.why:
        why_block = f"""
            <tr><td style="padding:8px 0 0 0;">
              <p style="margin:0;font-size:12px;color:rgba(255,255,255,0.45);line-height:1.55;font-style:italic;">
                Why: {html.escape(task.why)}
              </p>
            </td></tr>
        """

    return f"""
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:rgba(255,255,255,0.03);border-radius:10px;border-left:3px solid {color};margin:0 0 14px 0;">
          <tr><td style="padding:16px 18px;">
            <table width="100%" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td style="font-size:11px;font-weight:600;color:{color};text-transform:uppercase;letter-spacing:0.8px;">
                  #{idx} · {html.escape(task.task_type.value)} · {html.escape(task.priority.value)}
                </td>
                <td align="right" style="font-size:12px;color:rgba(255,255,255,0.4);">
                  {task.estimated_hours}h
                </td>
              </tr>
              <tr><td style="padding:6px 0 0 0;" colspan="2">
                <p style="margin:0;font-size:15px;font-weight:600;color:#f9fafb;line-height:1.4;">
                  {html.escape(task.title)}
                </p>
              </td></tr>
              <tr><td style="padding:8px 0 0 0;" colspan="2">
                <p style="margin:0;font-size:13px;color:rgba(255,255,255,0.7);line-height:1.6;">
                  {html.escape(task.description)}
                </p>
              </td></tr>
              {url_block}
              {resources_block}
              {why_block}
            </table>
          </td></tr>
        </table>
    """


def _render_resource_item(resource) -> str:  # type: ignore[no-untyped-def]
    """Render one resource as a row inside the resources_block table."""
    name = resource.name or resource.url
    if len(name) > 90:
        name = name[:87] + "..."
    note_html = ""
    if resource.note:
        note_html = (
            f'<span style="color:rgba(255,255,255,0.4);font-size:11px;">'
            f' — {html.escape(resource.note)}</span>'
        )
    return f"""
        <tr><td style="padding:3px 0;">
          <a href="{html.escape(resource.url)}" style="color:#60a5fa;text-decoration:none;font-size:13px;">
            {html.escape(name)}
          </a>{note_html}
        </td></tr>
    """


def render_text_fallback(plan: Plan) -> str:
    """Plain-text fallback for clients that don't render HTML."""
    lines = [
        f"GUIDE — {plan.date}",
        f"{plan.bug_class_name} · {plan.phase.value.upper()} phase · {plan.target_hours}h target",
        "",
    ]
    if plan.rationale:
        lines.append("Why this plan:")
        lines.append(plan.rationale)
        lines.append("")
    lines.append(f"Tasks ({len(plan.tasks)}):")
    for i, t in enumerate(plan.tasks, 1):
        lines.append("")
        lines.append(f"#{i} [{t.task_type.value}] {t.title} ({t.estimated_hours}h)")
        lines.append(t.description)
        if t.primary_resource_url:
            anchor_name = t.primary_resource_name or t.primary_resource_url
            lines.append(f"  → {anchor_name}")
            lines.append(f"    {t.primary_resource_url}")
        if t.resources:
            lines.append(f"  Resources ({len(t.resources)}):")
            for r in t.resources:
                tail = f" — {r.note}" if r.note else ""
                name = r.name or r.url
                lines.append(f"    • {name}{tail}")
                lines.append(f"      {r.url}")
        if t.why:
            lines.append(f"  Why: {t.why}")
    if plan.tools_section:
        lines.append("")
        lines.append(f"Tools for Hunting ({len(plan.tools_section)}):")
        for tool in plan.tools_section:
            name = tool.name or tool.url
            lines.append(f"  • {name}")
            if tool.note:
                lines.append(f"    {tool.note}")
            lines.append(f"    {tool.url}")
    lines.append("")
    lines.append("Reply with: '1: done 2.5h — learned X' / '2: skip — too easy'")
    return "\n".join(lines)
