"""Shared Streamlit entry point for all research projects."""

import streamlit as st

from projects.leap_study.app import render as render_leap_study

# Register future projects here; each project owns its page and controls.
PROJECTS = {"Leap Study": render_leap_study}

st.set_page_config(page_title="Bandalytics", page_icon="🏀", layout="wide")
st.sidebar.title("Bandalytics")
st.sidebar.caption("by Bandwagon Breaks")
project = st.sidebar.selectbox("Project", list(PROJECTS), key="project")
PROJECTS[project]()
