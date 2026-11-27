"""Dual-Theme Design System, Shared Components & Safe Formatters."""

from __future__ import annotations

import html
from typing import Any, Dict, List, Optional, Sequence, Tuple

import streamlit as st

from app.schemas.applicant import EligibilityResult
from app.ui.state import STATE_UI_THEME

THEME_PALETTES: Dict[str, Dict[str, str]] = {
    "light": {
        "bg": "#F3F6FA",
        "surface": "#FFFFFF",
        "surface_alt": "#F8FAFC",
        "surface_hover": "#F1F5F9",
        "border": "#E2E8F0",
        "border_strong": "#CBD5E1",
        "text": "#0F172A",
        "text_secondary": "#334155",
        "muted": "#64748B",
        "primary": "#3730A3",
        "primary_hover": "#312E81",
        "primary_soft": "#EEF2FF",
        "primary_text": "#3730A3",
        "teal": "#0D9488",
        "teal_soft": "#CCFBF1",
        "amber": "#D97706",
        "coral": "#E11D48",
        "purple": "#7C3AED",
        "success_bg": "#ECFDF5",
        "success_border": "#A7F3D0",
        "success_fg": "#065F46",
        "warning_bg": "#FFFBEB",
        "warning_border": "#FDE68A",
        "warning_fg": "#92400E",
        "danger_bg": "#FEF2F2",
        "danger_border": "#FECACA",
        "danger_fg": "#991B1B",
        "info_bg": "#EEF2FF",
        "info_border": "#C7D2FE",
        "info_fg": "#3730A3",
        "purple_bg": "#F5F3FF",
        "purple_border": "#DDD6FE",
        "purple_fg": "#5B21B6",
        "teal_bg": "#F0FDFA",
        "teal_border": "#99F6E4",
        "teal_fg": "#115E59",
        "neutral_bg": "#F1F5F9",
        "neutral_border": "#CBD5E1",
        "neutral_fg": "#334155",
        "shadow": "0 1px 2px rgba(15, 23, 42, 0.05)",
        "input_bg": "#FFFFFF",
        "color_scheme": "light",
    },
    "dark": {
        "bg": "#0B1220",
        "surface": "#111C2E",
        "surface_alt": "#162238",
        "surface_hover": "#1D2C47",
        "border": "#24324A",
        "border_strong": "#334666",
        "text": "#F1F5F9",
        "text_secondary": "#CBD5E1",
        "muted": "#94A3B8",
        "primary": "#6366F1",
        "primary_hover": "#818CF8",
        "primary_soft": "rgba(99, 102, 241, 0.16)",
        "primary_text": "#A5B4FC",
        "teal": "#2DD4BF",
        "teal_soft": "rgba(45, 212, 191, 0.15)",
        "amber": "#FBBF24",
        "coral": "#FB7185",
        "purple": "#A78BFA",
        "success_bg": "rgba(16, 185, 129, 0.15)",
        "success_border": "rgba(16, 185, 129, 0.35)",
        "success_fg": "#6EE7B7",
        "warning_bg": "rgba(245, 158, 11, 0.15)",
        "warning_border": "rgba(245, 158, 11, 0.35)",
        "warning_fg": "#FCD34D",
        "danger_bg": "rgba(244, 63, 94, 0.16)",
        "danger_border": "rgba(244, 63, 94, 0.38)",
        "danger_fg": "#FDA4AF",
        "info_bg": "rgba(99, 102, 241, 0.18)",
        "info_border": "rgba(129, 140, 248, 0.38)",
        "info_fg": "#C7D2FE",
        "purple_bg": "rgba(167, 139, 250, 0.16)",
        "purple_border": "rgba(167, 139, 250, 0.36)",
        "purple_fg": "#DDD6FE",
        "teal_bg": "rgba(45, 212, 191, 0.15)",
        "teal_border": "rgba(45, 212, 191, 0.36)",
        "teal_fg": "#5EEAD4",
        "neutral_bg": "rgba(148, 163, 184, 0.14)",
        "neutral_border": "#334666",
        "neutral_fg": "#CBD5E1",
        "shadow": "0 2px 6px rgba(2, 6, 23, 0.45)",
        "input_bg": "#0F1829",
        "color_scheme": "dark",
    },
}


def _esc(val: Any) -> str:
    """Safely HTML-escape any dynamic text rendered inside custom markup."""
    return html.escape("" if val is None else str(val), quote=True)


def get_ui_theme() -> str:
    """Return active normalized UI theme ('light' or 'dark')."""
    raw = str(st.session_state.get(STATE_UI_THEME, "light")).strip().lower()
    return "dark" if raw == "dark" else "light"


def get_theme_tokens(theme: Optional[str] = None) -> Dict[str, str]:
    """Return active CSS token dictionary for Light or Dark mode."""
    resolved = theme if theme in THEME_PALETTES else get_ui_theme()
    return THEME_PALETTES[resolved]


def apply_fintech_styles(theme: Optional[str] = None) -> None:
    """Inject dual-theme CSS variables, native widget overrides, and reusable design primitives."""
    t = get_theme_tokens(theme)
    st.markdown(
        f"""
        <style>
        :root {{
            --bank-bg: {t["bg"]};
            --bank-surface: {t["surface"]};
            --bank-surface-alt: {t["surface_alt"]};
            --bank-surface-hover: {t["surface_hover"]};
            --bank-border: {t["border"]};
            --bank-border-strong: {t["border_strong"]};
            --bank-text: {t["text"]};
            --bank-text-secondary: {t["text_secondary"]};
            --bank-muted: {t["muted"]};
            --bank-primary: {t["primary"]};
            --bank-primary-hover: {t["primary_hover"]};
            --bank-primary-soft: {t["primary_soft"]};
            --bank-primary-text: {t["primary_text"]};
            --bank-teal: {t["teal"]};
            --bank-amber: {t["amber"]};
            --bank-coral: {t["coral"]};
            --bank-purple: {t["purple"]};
            --bank-success-bg: {t["success_bg"]};
            --bank-success-border: {t["success_border"]};
            --bank-success-fg: {t["success_fg"]};
            --bank-warning-bg: {t["warning_bg"]};
            --bank-warning-border: {t["warning_border"]};
            --bank-warning-fg: {t["warning_fg"]};
            --bank-danger-bg: {t["danger_bg"]};
            --bank-danger-border: {t["danger_border"]};
            --bank-danger-fg: {t["danger_fg"]};
            --bank-info-bg: {t["info_bg"]};
            --bank-info-border: {t["info_border"]};
            --bank-info-fg: {t["info_fg"]};
            --bank-purple-bg: {t["purple_bg"]};
            --bank-purple-border: {t["purple_border"]};
            --bank-purple-fg: {t["purple_fg"]};
            --bank-teal-bg: {t["teal_bg"]};
            --bank-teal-border: {t["teal_border"]};
            --bank-teal-fg: {t["teal_fg"]};
            --bank-neutral-bg: {t["neutral_bg"]};
            --bank-neutral-border: {t["neutral_border"]};
            --bank-neutral-fg: {t["neutral_fg"]};
            --bank-shadow: {t["shadow"]};
            --bank-input-bg: {t["input_bg"]};
            color-scheme: {t["color_scheme"]};
        }}

        /* App canvas, header & sidebar */
        .stApp,
        [data-testid="stAppViewContainer"] {{
            background-color: var(--bank-bg);
            color: var(--bank-text);
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }}
        [data-testid="stHeader"] {{
            background-color: var(--bank-bg);
        }}
        [data-testid="stSidebar"] {{
            background-color: var(--bank-surface);
            border-right: 1px solid var(--bank-border);
            color: var(--bank-text);
        }}
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] span,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] small {{
            color: var(--bank-text);
        }}
        .block-container {{
            max-width: 1360px;
            padding-top: 1.4rem;
            padding-bottom: 2.5rem;
        }}

        /* Typography & Markdown consistency across both themes */
        .stApp p, .stApp li, .stApp label, .stApp h1, .stApp h2, .stApp h3, .stApp h4 {{
            color: var(--bank-text);
        }}
        [data-testid="stCaptionContainer"],
        [data-testid="stCaptionContainer"] p {{
            color: var(--bank-muted) !important;
        }}
        .stApp code {{
            background-color: var(--bank-surface-alt);
            color: var(--bank-primary-text);
            border: 1px solid var(--bank-border);
            border-radius: 4px;
            padding: 0.08rem 0.32rem;
        }}
        hr {{
            border-color: var(--bank-border) !important;
        }}

        /* Native bordered containers & metrics */
        [data-testid="stVerticalBlockBorderWrapper"] {{
            background-color: var(--bank-surface);
            border-color: var(--bank-border) !important;
            border-radius: 10px !important;
            box-shadow: var(--bank-shadow);
        }}
        [data-testid="stMetric"] {{
            background-color: var(--bank-surface);
            border: 1px solid var(--bank-border);
            border-radius: 8px;
            padding: 0.75rem 0.9rem;
            box-shadow: var(--bank-shadow);
        }}
        [data-testid="stMetricLabel"] p {{
            font-size: 0.78rem !important;
            color: var(--bank-muted) !important;
            font-weight: 600 !important;
        }}
        [data-testid="stMetricValue"] {{
            font-size: 1.3rem !important;
            color: var(--bank-text) !important;
            font-weight: 700 !important;
        }}

        /* Inputs, Selectboxes, Textareas, Expanders & File Uploader */
        .stTextInput input,
        .stNumberInput input,
        .stTextArea textarea,
        .stDateInput input,
        [data-baseweb="input"],
        [data-baseweb="input"] > div,
        [data-baseweb="base-input"],
        [data-baseweb="base-input"] > div,
        [data-baseweb="textarea"],
        [data-baseweb="textarea"] > div {{
            background-color: var(--bank-input-bg) !important;
            color: var(--bank-text) !important;
            border-color: var(--bank-border-strong) !important;
            border-radius: 7px !important;
        }}
        .stTextInput input::placeholder,
        .stNumberInput input::placeholder,
        .stTextArea textarea::placeholder {{
            color: var(--bank-muted) !important;
            opacity: 1 !important;
        }}
        [data-baseweb="select"],
        [data-baseweb="select"] div {{
            background-color: var(--bank-input-bg) !important;
            color: var(--bank-text) !important;
            border-color: var(--bank-border-strong) !important;
        }}
        [data-baseweb="select"] > div {{
            border-radius: 7px !important;
        }}
        [data-baseweb="select"] span,
        [data-baseweb="select"] input,
        [data-baseweb="select"] svg {{
            color: var(--bank-text) !important;
            fill: var(--bank-text) !important;
        }}
        [data-testid="stNumberInputContainer"],
        [data-testid="stNumberInputContainer"] > div {{
            background-color: var(--bank-input-bg) !important;
            border-color: var(--bank-border-strong) !important;
            border-radius: 7px !important;
        }}
        [data-baseweb="popover"],
        [data-baseweb="menu"] {{
            background-color: var(--bank-surface) !important;
            color: var(--bank-text) !important;
            border: 1px solid var(--bank-border-strong) !important;
        }}
        [data-baseweb="menu"] li,
        [data-baseweb="menu"] [role="option"] {{
            background-color: var(--bank-surface) !important;
            color: var(--bank-text) !important;
        }}
        [data-baseweb="menu"] [role="option"]:hover {{
            background-color: var(--bank-surface-hover) !important;
        }}
        .stNumberInput button,
        [data-testid="stNumberInputStepDown"],
        [data-testid="stNumberInputStepUp"] {{
            background-color: var(--bank-surface-alt) !important;
            color: var(--bank-text) !important;
            border-color: var(--bank-border) !important;
        }}
        [data-testid="stNumberInputStepDown"] svg,
        [data-testid="stNumberInputStepUp"] svg,
        [data-testid="stTooltipHoverTarget"] svg {{
            color: var(--bank-muted) !important;
            fill: var(--bank-muted) !important;
        }}
        [data-baseweb="radio"] > div:first-child {{
            background-color: var(--bank-surface-alt) !important;
            border: 2px solid var(--bank-border-strong) !important;
        }}
        [data-baseweb="radio"][aria-checked="true"] > div:first-child {{
            border-color: var(--bank-primary) !important;
            background-color: var(--bank-primary) !important;
        }}
        [data-testid="stFileUploader"] section {{
            background-color: var(--bank-surface-alt) !important;
            border: 1px dashed var(--bank-border-strong) !important;
            color: var(--bank-text) !important;
            border-radius: 8px !important;
        }}
        [data-testid="stExpander"] {{
            background-color: var(--bank-surface) !important;
            border: 1px solid var(--bank-border) !important;
            border-radius: 8px !important;
        }}
        [data-testid="stExpander"] summary,
        [data-testid="stExpander"] summary p {{
            color: var(--bank-text) !important;
        }}

        /* Tabs */
        button[role="tab"] {{
            color: var(--bank-muted) !important;
            font-weight: 500 !important;
        }}
        button[role="tab"][aria-selected="true"] {{
            color: var(--bank-primary-text) !important;
            font-weight: 600 !important;
            border-bottom-color: var(--bank-primary) !important;
        }}

        /* Buttons */
        .stButton button[kind="primary"] {{
            background-color: var(--bank-primary) !important;
            border-color: var(--bank-primary) !important;
            color: #FFFFFF !important;
            border-radius: 7px !important;
            font-weight: 600 !important;
        }}
        .stButton button[kind="primary"] p,
        .stButton button[kind="primary"] span {{
            color: #FFFFFF !important;
        }}
        .stButton button[kind="primary"]:hover {{
            background-color: var(--bank-primary-hover) !important;
            border-color: var(--bank-primary-hover) !important;
        }}
        .stButton button[kind="secondary"] {{
            background-color: var(--bank-surface) !important;
            border: 1px solid var(--bank-border-strong) !important;
            color: var(--bank-text) !important;
            border-radius: 7px !important;
            font-weight: 500 !important;
        }}
        .stButton button[kind="secondary"]:hover {{
            background-color: var(--bank-surface-hover) !important;
            border-color: var(--bank-primary) !important;
        }}

        /* Alerts in both themes */
        [data-testid="stAlert"] {{
            background-color: var(--bank-surface-alt) !important;
            border: 1px solid var(--bank-border) !important;
            color: var(--bank-text) !important;
            border-radius: 8px !important;
        }}

        /* ---------------- Custom Reusable Banking Primitives ---------------- */
        .banking-brand {{
            display: flex;
            align-items: center;
            gap: 0.6rem;
            padding-bottom: 0.8rem;
            margin-bottom: 0.75rem;
            border-bottom: 1px solid var(--bank-border);
        }}
        .banking-brand-mark {{
            width: 32px;
            height: 32px;
            border-radius: 8px;
            background-color: var(--bank-primary);
            color: #FFFFFF;
            font-weight: 700;
            font-size: 0.85rem;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
            letter-spacing: 0.03em;
        }}
        .banking-brand-title {{
            font-size: 0.98rem;
            font-weight: 700;
            color: var(--bank-text);
            line-height: 1.2;
        }}
        .banking-brand-sub {{
            font-size: 0.72rem;
            color: var(--bank-muted);
            margin-top: 0.1rem;
        }}
        .banking-sidebar-section {{
            font-size: 0.68rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.07em;
            color: var(--bank-muted);
            margin: 0.45rem 0 0.35rem 0;
        }}
        .banking-session-card {{
            background-color: var(--bank-surface-alt);
            border: 1px solid var(--bank-border);
            border-radius: 8px;
            padding: 0.6rem 0.75rem;
            margin-bottom: 0.45rem;
        }}
        .banking-session-name {{
            font-size: 0.85rem;
            font-weight: 600;
            color: var(--bank-text);
        }}
        .banking-session-role {{
            font-size: 0.74rem;
            color: var(--bank-muted);
            margin-top: 0.15rem;
        }}
        .banking-sidebar-note {{
            font-size: 0.73rem;
            color: var(--bank-muted);
            line-height: 1.4;
        }}

        /* Page Header & Breadcrumbs */
        .banking-breadcrumbs {{
            font-size: 0.76rem;
            font-weight: 500;
            color: var(--bank-muted);
            margin-bottom: 0.25rem;
        }}
        .banking-header {{
            margin-bottom: 1rem;
            padding-bottom: 0.75rem;
            border-bottom: 1px solid var(--bank-border);
        }}
        .banking-eyebrow {{
            font-size: 0.71rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--bank-primary-text);
            margin-bottom: 0.18rem;
        }}
        .banking-title {{
            font-size: 1.55rem;
            font-weight: 700;
            color: var(--bank-text);
            letter-spacing: -0.02em;
            line-height: 1.2;
            margin: 0;
        }}
        .banking-subtitle {{
            font-size: 0.9rem;
            color: var(--bank-text-secondary);
            margin-top: 0.25rem;
        }}
        .banking-section-title {{
            font-size: 1rem;
            font-weight: 600;
            color: var(--bank-text);
            margin: 0.1rem 0 0.12rem 0;
        }}
        .banking-section-sub {{
            font-size: 0.8rem;
            color: var(--bank-muted);
            margin-bottom: 0.65rem;
        }}

        /* KPI Row */
        .banking-kpi-grid {{
            display: grid;
            gap: 0.8rem;
            margin-bottom: 1rem;
        }}
        .banking-kpi-card {{
            background-color: var(--bank-surface);
            border: 1px solid var(--bank-border);
            border-radius: 10px;
            padding: 0.85rem 1rem;
            box-shadow: var(--bank-shadow);
            border-top: 3px solid var(--bank-border-strong);
        }}
        .banking-kpi-card.accent-indigo {{ border-top-color: var(--bank-primary); }}
        .banking-kpi-card.accent-teal {{ border-top-color: var(--bank-teal); }}
        .banking-kpi-card.accent-amber {{ border-top-color: var(--bank-amber); }}
        .banking-kpi-card.accent-coral {{ border-top-color: var(--bank-coral); }}
        .banking-kpi-label {{
            font-size: 0.73rem;
            font-weight: 600;
            color: var(--bank-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        .banking-kpi-value {{
            font-size: 1.6rem;
            font-weight: 700;
            color: var(--bank-text);
            font-variant-numeric: tabular-nums;
            margin: 0.25rem 0 0.15rem 0;
            line-height: 1.15;
        }}
        .banking-kpi-meta {{
            font-size: 0.76rem;
            color: var(--bank-text-secondary);
        }}

        /* Key-Value Definition Grid */
        .banking-kv-grid {{
            display: grid;
            gap: 0.75rem 1rem;
            background-color: var(--bank-surface);
            border: 1px solid var(--bank-border);
            border-radius: 9px;
            padding: 0.9rem 1rem;
            margin-bottom: 0.85rem;
            box-shadow: var(--bank-shadow);
        }}
        .banking-kv-item {{ min-width: 0; }}
        .banking-kv-label {{
            font-size: 0.73rem;
            font-weight: 600;
            color: var(--bank-muted);
            margin-bottom: 0.18rem;
        }}
        .banking-kv-val {{
            font-size: 0.94rem;
            font-weight: 600;
            color: var(--bank-text);
            line-height: 1.35;
            word-break: break-word;
            font-variant-numeric: tabular-nums;
        }}
        .banking-kv-sub {{
            font-size: 0.73rem;
            color: var(--bank-muted);
            margin-top: 0.14rem;
        }}

        /* Badges / Pills */
        .banking-pill {{
            display: inline-block;
            padding: 0.16rem 0.55rem;
            border-radius: 5px;
            font-size: 0.73rem;
            font-weight: 600;
            line-height: 1.35;
            border: 1px solid transparent;
            white-space: nowrap;
        }}
        .pill-success {{
            background-color: var(--bank-success-bg);
            border-color: var(--bank-success-border);
            color: var(--bank-success-fg);
        }}
        .pill-warning {{
            background-color: var(--bank-warning-bg);
            border-color: var(--bank-warning-border);
            color: var(--bank-warning-fg);
        }}
        .pill-danger {{
            background-color: var(--bank-danger-bg);
            border-color: var(--bank-danger-border);
            color: var(--bank-danger-fg);
        }}
        .pill-info {{
            background-color: var(--bank-info-bg);
            border-color: var(--bank-info-border);
            color: var(--bank-info-fg);
        }}
        .pill-teal {{
            background-color: var(--bank-teal-bg);
            border-color: var(--bank-teal-border);
            color: var(--bank-teal-fg);
        }}
        .pill-purple {{
            background-color: var(--bank-purple-bg);
            border-color: var(--bank-purple-border);
            color: var(--bank-purple-fg);
        }}
        .pill-neutral {{
            background-color: var(--bank-neutral-bg);
            border-color: var(--bank-neutral-border);
            color: var(--bank-neutral-fg);
        }}

        /* Pipeline Visual Track */
        .banking-pipeline-bar {{
            display: flex;
            width: 100%;
            height: 12px;
            border-radius: 6px;
            overflow: hidden;
            background-color: var(--bank-surface-alt);
            border: 1px solid var(--bank-border);
            margin: 0.5rem 0 0.85rem 0;
        }}
        .banking-pipeline-seg {{
            height: 100%;
            min-width: 4px;
        }}
        .banking-pipeline-grid {{
            display: grid;
            gap: 0.55rem;
        }}
        .banking-pipeline-stage {{
            background-color: var(--bank-surface-alt);
            border: 1px solid var(--bank-border);
            border-radius: 8px;
            padding: 0.55rem 0.7rem;
        }}
        .banking-pipeline-stage-top {{
            display: flex;
            align-items: center;
            gap: 0.35rem;
            font-size: 0.72rem;
            color: var(--bank-text-secondary);
            font-weight: 600;
            white-space: nowrap;
        }}
        .banking-dot {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            display: inline-block;
            flex-shrink: 0;
        }}
        .banking-pipeline-count {{
            font-size: 1.25rem;
            font-weight: 700;
            color: var(--bank-text);
            font-variant-numeric: tabular-nums;
            margin-top: 0.2rem;
        }}

        /* Wizard Progress Stepper */
        .banking-stepper {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.65rem;
            margin-bottom: 1rem;
        }}
        .banking-step {{
            background-color: var(--bank-surface);
            border: 1px solid var(--bank-border);
            border-radius: 8px;
            padding: 0.6rem 0.75rem;
        }}
        .banking-step.is-active {{
            border-color: var(--bank-primary);
            background-color: var(--bank-primary-soft);
        }}
        .banking-step.is-done {{
            border-color: var(--bank-success-border);
            background-color: var(--bank-success-bg);
        }}
        .banking-step-num {{
            font-size: 0.68rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: var(--bank-muted);
        }}
        .banking-step.is-active .banking-step-num {{ color: var(--bank-primary-text); }}
        .banking-step.is-done .banking-step-num {{ color: var(--bank-success-fg); }}
        .banking-step-title {{
            font-size: 0.84rem;
            font-weight: 600;
            color: var(--bank-text);
            margin-top: 0.12rem;
        }}

        /* Responsive Themed Banking Data Table */
        .banking-table-wrap {{
            width: 100%;
            overflow-x: auto;
            border: 1px solid var(--bank-border);
            border-radius: 8px;
            background-color: var(--bank-surface);
        }}
        .banking-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.83rem;
            color: var(--bank-text);
        }}
        .banking-table th {{
            text-align: left;
            padding: 0.58rem 0.75rem;
            font-size: 0.72rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            color: var(--bank-muted);
            background-color: var(--bank-surface-alt);
            border-bottom: 1px solid var(--bank-border);
            white-space: nowrap;
        }}
        .banking-table td {{
            padding: 0.58rem 0.75rem;
            border-bottom: 1px solid var(--bank-border);
            color: var(--bank-text);
            vertical-align: middle;
            font-variant-numeric: tabular-nums;
        }}
        .banking-table td:first-child,
        .banking-table td:last-child {{
            white-space: nowrap;
        }}
        .banking-table tr:last-child td {{
            border-bottom: none;
        }}
        .banking-table tbody tr:hover {{
            background-color: var(--bank-surface-hover);
        }}

        /* Recommendation & Advisory Cards */
        .banking-rec-card {{
            border-radius: 8px;
            padding: 0.75rem 0.9rem;
            border: 1px solid var(--bank-border);
            background-color: var(--bank-surface);
        }}
        .banking-rec-label {{
            font-size: 0.7rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            opacity: 0.85;
            margin-bottom: 0.18rem;
        }}
        .banking-rec-value {{
            font-size: 1.15rem;
            font-weight: 700;
            line-height: 1.25;
        }}
        .rec-approve {{
            background-color: var(--bank-success-bg);
            border-color: var(--bank-success-border);
            color: var(--bank-success-fg);
        }}
        .rec-reject {{
            background-color: var(--bank-danger-bg);
            border-color: var(--bank-danger-border);
            color: var(--bank-danger-fg);
        }}
        .rec-manual {{
            background-color: var(--bank-warning-bg);
            border-color: var(--bank-warning-border);
            color: var(--bank-warning-fg);
        }}
        .banking-banner {{
            border-radius: 8px;
            padding: 0.65rem 0.9rem;
            margin-bottom: 0.9rem;
            font-size: 0.84rem;
            line-height: 1.45;
            border: 1px solid var(--bank-border);
            background-color: var(--bank-surface);
        }}
        .banner-info {{
            background-color: var(--bank-info-bg);
            border-color: var(--bank-info-border);
            color: var(--bank-info-fg);
        }}
        .banner-warning {{
            background-color: var(--bank-warning-bg);
            border-color: var(--bank-warning-border);
            color: var(--bank-warning-fg);
        }}
        .banner-danger {{
            background-color: var(--bank-danger-bg);
            border-color: var(--bank-danger-border);
            color: var(--bank-danger-fg);
        }}
        .banking-factor {{
            background-color: var(--bank-surface-alt);
            border: 1px solid var(--bank-border);
            border-left-width: 3px;
            border-radius: 6px;
            padding: 0.5rem 0.75rem;
            margin-bottom: 0.45rem;
            font-size: 0.83rem;
            color: var(--bank-text);
            line-height: 1.4;
        }}
        .factor-positive {{ border-left-color: #10B981; }}
        .factor-negative {{ border-left-color: var(--bank-amber); }}
        .factor-blocking {{
            border-left-color: var(--bank-coral);
            background-color: var(--bank-danger-bg);
        }}
        .banking-empty {{
            background-color: var(--bank-surface-alt);
            border: 1px dashed var(--bank-border-strong);
            border-radius: 10px;
            padding: 1.35rem 1.25rem;
            text-align: center;
            color: var(--bank-text-secondary);
        }}
        .banking-empty-title {{
            font-size: 0.96rem;
            font-weight: 600;
            color: var(--bank-text);
            margin-bottom: 0.25rem;
        }}
        .banking-empty-sub {{
            font-size: 0.82rem;
            color: var(--bank-muted);
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def format_inr(val: Optional[float]) -> str:
    """Format numeric value in INR notation, preserving valid zero (0.0)."""
    if val is None:
        return "N/A"
    return f"₹{float(val):,.2f}"


def format_compact_status(raw: Optional[str]) -> str:
    """Format uppercase domain/review tokens into readable compact title labels."""
    val = str(raw or "").strip().upper()
    mapping = {
        "APPROVE": "Approve",
        "APPROVED": "Approved",
        "REJECT": "Reject",
        "REJECTED": "Rejected",
        "MANUAL_REVIEW": "Manual Review",
        "NOT_EVALUATED": "Not Evaluated",
        "AI_MANUAL_REVIEW": "AI Review",
        "AWAITING_HUMAN_DECISION": "Awaiting Decision",
        "MISSING_DOCUMENTS": "Missing Docs",
        "INCOMPLETE_DOCS": "Incomplete Docs",
        "PIPELINE_FAILURE": "Pipeline Failed",
        "CROSS_AGENT_CONFLICT": "Conflict",
        "HIGH_RISK": "High Risk",
        "BORDERLINE_RISK": "Borderline Risk",
        "PENDING": "Pending",
        "IN_REVIEW": "In Review",
        "ADDITIONAL_INFO_REQUESTED": "Info Requested",
        "INVESTIGATION_REQUIRED": "Investigation",
        "SUCCESS": "Completed",
        "PARTIAL_SUCCESS": "Partial",
        "FAILED": "Failed",
        "UNDERWRITTEN": "Underwritten",
        "INCOMPLETE": "Incomplete",
        "SYNTHETIC_CATALOG": "Catalog",
        "UNAVAILABLE": "Unavailable",
    }
    if val in mapping:
        return mapping[val]
    return val.replace("_", " ").title() if val else "—"


def status_variant_for(raw: Optional[str]) -> str:
    """Map an underwriting or review status string to a restrained semantic tone."""
    val = str(raw or "").strip().upper()
    if val in {
        "APPROVE",
        "APPROVED",
        "ELIGIBLE",
        "LOW",
        "NONE",
        "VALID",
        "SUCCESS",
        "COMPLETE",
    }:
        return "success"
    if val in {
        "REJECT",
        "REJECTED",
        "INELIGIBLE",
        "HIGH",
        "FAILED",
        "INVALID",
        "BLOCKING",
        "PIPELINE FAILED",
    }:
        return "danger"
    if val in {
        "MANUAL_REVIEW",
        "MANUAL REVIEW",
        "BORDERLINE",
        "MEDIUM",
        "PENDING",
        "ADDITIONAL_INFO_REQUESTED",
        "INFO REQUESTED",
        "INVESTIGATION_REQUIRED",
        "INVESTIGATION",
        "PARTIAL_SUCCESS",
        "INCOMPLETE",
        "INCOMPLETE DOCS",
        "MISSING DOCS",
        "UNAVAILABLE",
        "REVIEW_REQUIRED",
    }:
        return "warning"
    if val in {"IN_REVIEW", "IN REVIEW", "UNDERWRITTEN"}:
        return "info"
    if val in {"SYNTHETIC_CATALOG", "CATALOG", "SUBMITTED"}:
        return "teal"
    return "neutral"


def render_status_pill(label: str, variant: Optional[str] = None) -> str:
    """Return safe HTML markup for a restrained status pill."""
    tone = variant or status_variant_for(label)
    return f'<span class="banking-pill pill-{_esc(tone)}">{_esc(label)}</span>'


def render_breadcrumbs(items: Sequence[str]) -> None:
    """Render clean breadcrumb trail above page titles."""
    if not items:
        return
    trail = "  /  ".join(_esc(item) for item in items)
    st.markdown(
        f'<div class="banking-breadcrumbs">{trail}</div>',
        unsafe_allow_html=True,
    )


def render_page_header(
    eyebrow: str,
    title: str,
    subtitle: str = "",
    breadcrumbs: Optional[Sequence[str]] = None,
) -> None:
    """Render a consistent enterprise page header with optional breadcrumbs and subtitle."""
    if breadcrumbs:
        render_breadcrumbs(breadcrumbs)
    sub_html = (
        f'<div class="banking-subtitle">{_esc(subtitle)}</div>' if subtitle else ""
    )
    st.markdown(
        f"""
        <div class="banking-header">
            <div class="banking-eyebrow">{_esc(eyebrow)}</div>
            <div class="banking-title">{_esc(title)}</div>
            {sub_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_section_heading(title: str, subtitle: str = "") -> None:
    """Render a clean section heading and optional muted descriptor."""
    sub_html = (
        f'<div class="banking-section-sub">{_esc(subtitle)}</div>' if subtitle else ""
    )
    st.markdown(
        f'<div class="banking-section-title">{_esc(title)}</div>{sub_html}',
        unsafe_allow_html=True,
    )


def render_kpi_row(items: Sequence[Dict[str, Any]]) -> None:
    """Render compact, tabular-numeral KPI cards in a balanced horizontal grid."""
    if not items:
        return
    cols = len(items)
    cards = []
    for item in items:
        meta = item.get("meta")
        accent = item.get("accent", "indigo")
        meta_html = f'<div class="banking-kpi-meta">{_esc(meta)}</div>' if meta else ""
        cards.append(
            f'<div class="banking-kpi-card accent-{_esc(accent)}">'
            f'<div class="banking-kpi-label">{_esc(item.get("label", ""))}</div>'
            f'<div class="banking-kpi-value">{_esc(item.get("value", "—"))}</div>'
            f"{meta_html}"
            f"</div>"
        )
    st.markdown(
        f'<div class="banking-kpi-grid" style="grid-template-columns: repeat({cols}, minmax(0, 1fr));">'
        + "".join(cards)
        + "</div>",
        unsafe_allow_html=True,
    )


def render_kv_grid(
    items: Sequence[Tuple[str, str] | Tuple[str, str, str]],
    columns: int = 4,
) -> None:
    """Render a bordered definition grid without metric truncation."""
    if not items:
        return
    cells: List[str] = []
    for entry in items:
        label = entry[0]
        value = entry[1]
        sub = entry[2] if len(entry) > 2 else ""
        sub_html = f'<div class="banking-kv-sub">{_esc(sub)}</div>' if sub else ""
        cells.append(
            f'<div class="banking-kv-item">'
            f'<div class="banking-kv-label">{_esc(label)}</div>'
            f'<div class="banking-kv-val">{_esc(value)}</div>'
            f"{sub_html}"
            f"</div>"
        )
    st.markdown(
        f'<div class="banking-kv-grid" style="grid-template-columns: repeat({int(columns)}, minmax(0, 1fr));">'
        + "".join(cells)
        + "</div>",
        unsafe_allow_html=True,
    )


def render_wizard_progress(
    current_step: int, steps: Sequence[Tuple[int, str, str]]
) -> None:
    """Render structured 4-step wizard progress stepper."""
    cards: List[str] = []
    for step_num, short_title, desc in steps:
        if step_num < current_step:
            cls = "is-done"
            prefix = f"Step {step_num} · Completed"
        elif step_num == current_step:
            cls = "is-active"
            prefix = f"Step {step_num} · Current"
        else:
            cls = ""
            prefix = f"Step {step_num}"
        cards.append(
            f'<div class="banking-step {cls}" title="{_esc(desc)}">'
            f'<div class="banking-step-num">{_esc(prefix)}</div>'
            f'<div class="banking-step-title">{_esc(short_title)}</div>'
            f"</div>"
        )
    st.markdown(
        '<div class="banking-stepper">' + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )


def render_pipeline_visual(stages: Sequence[Dict[str, Any]]) -> None:
    """Render clean proportional pipeline bar and stage cards adapting to Light & Dark mode."""
    total = sum(int(s.get("count", 0)) for s in stages)
    if total > 0:
        segs = []
        for s in stages:
            cnt = int(s.get("count", 0))
            if cnt <= 0:
                continue
            pct = max(3.0, (cnt / total) * 100.0)
            color = _esc(s.get("color", "#3730A3"))
            segs.append(
                f'<div class="banking-pipeline-seg" style="width:{pct:.2f}%;background-color:{color};" '
                f'title="{_esc(s.get("label"))}: {cnt}"></div>'
            )
        st.markdown(
            '<div class="banking-pipeline-bar">' + "".join(segs) + "</div>",
            unsafe_allow_html=True,
        )

    stage_cards = []
    for s in stages:
        cnt = int(s.get("count", 0))
        color = _esc(s.get("color", "#3730A3"))
        stage_cards.append(
            f'<div class="banking-pipeline-stage">'
            f'<div class="banking-pipeline-stage-top">'
            f'<span class="banking-dot" style="background-color:{color};"></span>'
            f'<span>{_esc(s.get("label", ""))}</span>'
            f"</div>"
            f'<div class="banking-pipeline-count">{cnt}</div>'
            f"</div>"
        )
    st.markdown(
        f'<div class="banking-pipeline-grid" style="grid-template-columns: repeat({len(stages)}, minmax(0, 1fr));">'
        + "".join(stage_cards)
        + "</div>",
        unsafe_allow_html=True,
    )


def render_banking_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    pill_columns: Optional[set[int]] = None,
    empty_message: str = "No records match the current selection.",
) -> None:
    """Render an HTML-escaped, theme-adaptive enterprise data table without canvas dark-mode glare."""
    if not rows:
        render_empty_state("No Records", empty_message)
        return
    pill_cols = pill_columns or set()
    th_html = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    tr_list: List[str] = []
    for row in rows:
        tds: List[str] = []
        for idx, cell in enumerate(row):
            if idx in pill_cols and str(cell).strip() not in {"", "—", "N/A"}:
                tds.append(f"<td>{render_status_pill(str(cell))}</td>")
            else:
                tds.append(f"<td>{_esc(cell)}</td>")
        tr_list.append("<tr>" + "".join(tds) + "</tr>")

    st.markdown(
        f"""
        <div class="banking-table-wrap">
            <table class="banking-table">
                <thead><tr>{th_html}</tr></thead>
                <tbody>{''.join(tr_list)}</tbody>
            </table>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_empty_state(title: str, description: str) -> None:
    """Render restrained banking empty-state card."""
    st.markdown(
        f"""
        <div class="banking-empty">
            <div class="banking-empty-title">{_esc(title)}</div>
            <div class="banking-empty-sub">{_esc(description)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_alert_box(title: str, message: str, variant: str = "info") -> None:
    """Render styled notice/alert banner across Light and Dark themes."""
    tone = variant if variant in {"info", "warning", "danger"} else "info"
    st.markdown(
        f"""
        <div class="banking-banner banner-{tone}">
            <strong>{_esc(title)}:</strong> {_esc(message)}
        </div>
        """,
        unsafe_allow_html=True,
    )


def format_eligibility_metrics_summary(elig_res: EligibilityResult) -> str:
    """Format max eligible loan amount and DTI summary line for display."""
    dti_str = (
        f"`{elig_res.dti_ratio:.1f}%`" if elig_res.dti_ratio is not None else "`N/A`"
    )
    return (
        f"**Max Permitted Loan:** {format_inr(elig_res.max_eligible_amount)} | "
        f"**Calculated DTI:** {dti_str}"
    )


def render_hitl_banner() -> None:
    """Display mandatory human-in-the-loop governance banner."""
    render_alert_box(
        "Human Review Required",
        "AI underwriting outputs provide advisory decision support only. Final credit approval or rejection remains with an authorized human underwriter.",
        variant="info",
    )


def render_recommendation_badge(raw_outcome: Optional[str]) -> None:
    """Render mapped categorical AI recommendation card cleanly without fabrication."""
    val = str(raw_outcome or "MANUAL_REVIEW").upper()
    if val == "APPROVE":
        cls = "rec-approve"
        text = "Approve"
    elif val == "REJECT":
        cls = "rec-reject"
        text = "Reject"
    else:
        cls = "rec-manual"
        text = "Manual Review"
    st.markdown(
        f"""
        <div class="banking-rec-card {_esc(cls)}">
            <div class="banking-rec-label">AI Recommendation</div>
            <div class="banking-rec-value">{_esc(text)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def format_risk_score_display(risk_score: Optional[float]) -> str:
    """Never render an unavailable risk score as 0.0."""
    if risk_score is None:
        return "Unavailable"
    return f"{float(risk_score):.1f} / 100"


def format_fraud_status_display(fraud_status: Optional[str]) -> str:
    """Never equate an unavailable fraud assessment to NONE/clean."""
    if not fraud_status or str(fraud_status).upper() == "UNAVAILABLE":
        return "UNAVAILABLE (Inspection Required)"
    return str(fraud_status).upper()


def render_factor_cards(
    positive_factors: List[str],
    negative_factors: List[str],
    blocking_factors: List[str],
) -> None:
    """Render structured three-column factor breakdown cards."""
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Positive Factors**")
        if positive_factors:
            for item in positive_factors:
                st.markdown(
                    f'<div class="banking-factor factor-positive">{_esc(item)}</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.caption("No positive factors recorded.")
    with c2:
        st.markdown("**Negative Factors**")
        if negative_factors:
            for item in negative_factors:
                st.markdown(
                    f'<div class="banking-factor factor-negative">{_esc(item)}</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.caption("No negative factors recorded.")
    with c3:
        st.markdown("**Blocking Safeguards**")
        if blocking_factors:
            for item in blocking_factors:
                st.markdown(
                    f'<div class="banking-factor factor-blocking">{_esc(item)}</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.caption("No blocking conditions triggered.")


def render_conflicts_panel(conflicts: List[Dict[str, Any]]) -> None:
    """Render cross-agent consistency conflicts explicitly."""
    if not conflicts:
        st.success("No cross-agent consistency contradictions detected.")
        return
    st.error(f"{len(conflicts)} cross-agent consistency conflict(s) detected:")
    for conflict in conflicts:
        cid = conflict.get("conflict_id", "CONFLICT")
        sev = conflict.get("severity", "BLOCKING")
        desc = conflict.get("description", "")
        sources = ", ".join(conflict.get("conflicting_sources", [])) or "N/A"
        auth = conflict.get("authoritative_source", "N/A")
        st.markdown(
            f"- **`{cid}` ({sev})**: {desc}  \n"
            f"  *Sources:* `{sources}` | *Authoritative:* `{auth}`"
        )


def render_human_vs_ai_summary_panel(case_summary: Dict[str, Any]) -> None:
    """Display AI recommendation, pipeline status, human review status, and human decision separately."""
    ai_rec = format_compact_status(case_summary.get("ai_recommendation", "NOT_EVALUATED"))
    pipe_st = format_compact_status(case_summary.get("pipeline_status", "NOT_RUN"))
    rev_st = format_compact_status(case_summary.get("human_review_status", "PENDING"))
    hum_dec = case_summary.get("human_decision")
    latest_rev = case_summary.get("latest_review")

    hum_dec_disp = format_compact_status(hum_dec) if hum_dec else "Not yet recorded"
    reviewer_note = (
        f"By {latest_rev['reviewer_id']} ({str(latest_rev.get('review_timestamp', ''))[:19].replace('T', ' ')} UTC)"
        if latest_rev
        else "Awaiting underwriter action"
    )

    render_kv_grid(
        [
            ("1. AI Recommendation", ai_rec, "Advisory decision support only"),
            ("2. Pipeline Execution", pipe_st, "Automated workflow health"),
            ("3. Human Review Status", rev_st, "Current queue state"),
            ("4. Final Human Decision", hum_dec_disp, reviewer_note),
        ],
        columns=4,
    )

    if latest_rev and latest_rev.get("reviewer_user_id"):
        st.caption(
            f"Verified Reviewer: `{latest_rev.get('reviewer_username') or latest_rev['reviewer_id']}` "
            f"(ID `{latest_rev['reviewer_user_id']}`, Role `{latest_rev.get('reviewer_role') or 'N/A'}`)"
        )
    else:
        st.caption(
            "Local session attribution active. Sign in via the sidebar or use the FastAPI `/api/v1` backend for verified JWT/RBAC attribution."
        )
