# ui_components.py

import streamlit as st

def _get_safe_float(value, default=0.0):
    """Safely converts a value to a float, returning a default if conversion fails."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

def render_progress_card(item: dict, container, lang_code: str = 'en', key_prefix: str = 'card'):
    """
    Renders a single AI progress item with multi-lingual support
    and a fixed layout for the importance score.
    """
    analysis = item.get('analysis_data', {})
    content_lang = analysis.get(lang_code, analysis.get('en', {}))
    ranking = analysis.get('ranking', {})
    scores = ranking.get('scores', {})
    
    try:
        with container:
            # --- Header ---
            header_cols = st.columns([7, 1])
            with header_cols[0]:
                st.subheader(content_lang.get('title', item.get('title', 'Untitled')))
                st.caption(f"Source: **{item.get('source', 'N/A')}** | Published: **{item.get('published_date', 'N/A')}**")
            
            # --- Importance Score ---
            score_value = _get_safe_float(ranking.get('overall_importance_score'))
            header_cols[1].metric("Importance", f"{score_value:.1f}/10")

            # --- Progress Bar ---
            st.progress(
                int(score_value * 10),
                text=f"💡 {content_lang.get('overall_importance_justification', 'No justification available.')}"
            )
            st.write("") # Spacer

            # --- Core Summaries ---
            tab_what, tab_why, tab_how = st.tabs(["**What's New?**", "**Why It Matters?**", "**How It Works?**"])
            tab_what.write(content_lang.get('what_is_new', 'Summary not available.'))
            tab_why.write(content_lang.get('why_it_matters', 'Impact statement not available.'))
            tab_how.write(content_lang.get('how_it_works', 'Explanation not available.'))

            # --- Expander for Details & Actions ---
            with st.expander("View Detailed Scores & Actions"):
                st.markdown("---")
                st.markdown("###### AI-Generated Score Breakdown (English Only)")
                
                s_col1, s_col2, s_col3, s_col4 = st.columns(4)
                s_col1.metric("Novelty", f"{_get_safe_float(scores.get('breakthrough_novelty', {}).get('score')):.1f}/10")
                s_col2.metric("Human Impact", f"{_get_safe_float(scores.get('human_impact', {}).get('score')):.1f}/10")
                s_col3.metric("Field Influence", f"{_get_safe_float(scores.get('field_influence', {}).get('score')):.1f}/10")
                s_col4.metric("Maturity", f"{_get_safe_float(scores.get('technical_maturity', {}).get('score')):.1f}/10")
                
                st.markdown("###### English Keywords")
                st.write(' '.join([f"`{kw}`" for kw in analysis.get('keywords', [])]))
                
                st.divider()
                a_col1, a_col2 = st.columns(2)
                a_col1.link_button("🔗 Go to Source", item.get('url', '#'), use_container_width=True)
                
                button_key = f"{key_prefix}_flag_{item.get('id')}"
                if a_col2.button("🚩 Flag for Review", key=button_key, use_container_width=True, type="secondary"):
                    st.session_state[f"flagging_item_id_{key_prefix}"] = item.get('id')
                    st.rerun()

    except Exception as e:
        st.error(f"Failed to render card for item ID {item.get('id')}: {e}", icon="🚨")
        print(f"ERROR in render_progress_card: {e}")
        print(f"Item data that caused error: {item}")

def render_admin_dashboard(data):
    """Renders the admin dashboard."""
    st.title("Admin Dashboard")
    # ... (implementation for admin dashboard) ...

