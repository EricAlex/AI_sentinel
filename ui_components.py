# ui_components.py

import streamlit as st

def render_progress_card(item: dict, container):
    """
    Renders a single AI progress item in a visually appealing card format within a given container.
    
    Args:
        item (dict): A dictionary containing the flattened data for one progress item.
        container: The Streamlit container (e.g., st.container() or st) to draw into.
    """
    with container:
        # --- Header Section ---
        col1, col2 = st.columns([4, 1])
        with col1:
            st.subheader(item.get('title', 'Untitled'))
            st.caption(f"Source: **{item.get('source', 'N/A')}** | Published: **{item.get('published_date', 'N/A')}**")
        with col2:
            st.metric("Importance", f"{item.get('overall_importance_score', 0.0):.1f}/10")

        # --- Main Progress Bar and Justification ---
        st.progress(
            int(item.get('overall_importance_score', 0.0) * 10),
            text=f":bulb: {item.get('overall_importance_justification', 'No justification available.')}"
        )
        st.write("") # Spacer

        # --- Core Summaries ---
        tab_what, tab_why, tab_how = st.tabs(["**What's New?**", "**Why It Matters?**", "**How It Works?**"])
        with tab_what:
            st.write(item.get('summary_what_is_new', 'Not available.'))
        with tab_why:
            st.write(item.get('summary_why_it_matters', 'Not available.'))
        with tab_how:
            st.write(item.get('summary_how_it_works', 'Not available.'))

        # --- Expander for Detailed Scores and Actions ---
        with st.expander("Show Detailed Scores & Actions"):
            st.markdown("---")
            st.markdown("###### AI-Generated Score Breakdown")
            
            s_col1, s_col2, s_col3, s_col4 = st.columns(4)
            s_col1.metric("Novelty", f"{item.get('novelty_score', 0)}/10")
            s_col2.metric("Human Impact", f"{item.get('human_impact_score', 0)}/10")
            s_col3.metric("Field Influence", f"{item.get('field_influence_score', 0)}/10")
            s_col4.metric("Maturity", f"{item.get('technical_maturity_score', 0)}/10")
            
            st.markdown("###### Keywords")
            keywords = item.get('keywords', [])
            if keywords:
                st.write(' '.join([f"`{kw}`" for kw in keywords]))
            else:
                st.caption("No keywords available.")
            
            st.markdown("---")
            # --- Actions Section ---
            a_col1, a_col2 = st.columns(2)
            with a_col1:
                st.link_button("🔗 Go to Source", item.get('url', '#'), use_container_width=True)
            with a_col2:
                # This button sets a session state variable that the main app.py will detect
                if st.button("🚩 Flag for Review", key=f"flag_{item.get('id')}", use_container_width=True, type="secondary"):
                    st.session_state.flagging_item_id = item.get('id')
                    st.rerun() # Rerun to make the form appear immediately