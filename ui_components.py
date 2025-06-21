# ui_components.py

import streamlit as st

def render_progress_card(item: dict, container, lang_code: str = 'en', key_prefix: str = 'card'):
    """
    Renders a single AI progress item with multi-lingual support
    and a fixed layout for the importance score.
    """
    analysis = item.get('analysis_data', {})
    content_lang = analysis.get(lang_code, analysis.get('en', {}))
    ranking = analysis.get('ranking', {})
    scores = ranking.get('scores', {})
    
    with container:
        # --- Header with columns for layout ---
        header_cols = st.columns([7, 1])
        
        with header_cols[0]:
            st.subheader(content_lang.get('title', 'Untitled'))
            st.caption(f"Source: **{item.get('source', 'N/A')}** | Published: **{item.get('published_date', 'N/A')}**")
        
        with header_cols[1]:
            # 1. Get the score, which might be a string like "8.7". Default to "0.0".
            score_value_str = ranking.get('overall_importance_score', "0.0")
            # 2. Safely convert it to a float.
            try:
                score_value_float = float(score_value_str)
            except (ValueError, TypeError):
                score_value_float = 0.0 # Default to 0.0 if conversion fails
            # 3. Now, format the guaranteed float value.
            st.metric("Importance", f"{score_value_float:.1f}/10")

        # --- Progress Bar with translated justification ---
        # Also apply the same robust float conversion here.
        progress_score_str = ranking.get('overall_importance_score', "0.0")
        try:
            progress_score_float = float(progress_score_str)
        except (ValueError, TypeError):
            progress_score_float = 0.0
            
        st.progress(
            int(progress_score_float * 10),
            text=f"💡 {content_lang.get('overall_importance_justification', 'No justification available.')}"
        )
        st.write("")

        # --- Core Summaries ---
        tab_what, tab_why, tab_how = st.tabs(["**What's New?**", "**Why It Matters?**", "**How It Works?**"])
        with tab_what:
            st.write(content_lang.get('what_is_new', 'Summary not available.'))
        with tab_why:
            st.write(content_lang.get('why_it_matters', 'Impact statement not available.'))
        with tab_how:
            st.write(content_lang.get('how_it_works', 'Explanation not available.'))

        # --- Expander for Detailed Scores and Actions ---
        with st.expander("Show Detailed Scores (in English) & Actions"):
            st.markdown("---")
            st.markdown("###### AI-Generated Score Breakdown")
            
            s_col1, s_col2, s_col3, s_col4 = st.columns(4)
            # Apply the same robust casting to the individual scores
            s_col1.metric("Novelty", f"{float(scores.get('breakthrough_novelty', {}).get('score', 0))}/10")
            s_col2.metric("Human Impact", f"{float(scores.get('human_impact', {}).get('score', 0))}/10")
            s_col3.metric("Field Influence", f"{float(scores.get('field_influence', {}).get('score', 0))}/10")
            s_col4.metric("Maturity", f"{float(scores.get('technical_maturity', {}).get('score', 0))}/10")
            
            st.markdown("###### English Keywords")
            st.write(' '.join([f"`{kw}`" for kw in analysis.get('keywords', [])]))
            
            st.divider()
            a_col1, a_col2 = st.columns(2)
            with a_col1:
                st.link_button("🔗 Go to Source", item.get('url', '#'), use_container_width=True)
            with a_col2:
                button_key = f"{key_prefix}_flag_{item.get('id')}"
                if st.button("🚩 Flag for Review", key=button_key, use_container_width=True, type="secondary"):
                    # We also use a unique key for the session state variable
                    st.session_state[f"flagging_item_id_{key_prefix}"] = item.get('id')
                    st.rerun()
