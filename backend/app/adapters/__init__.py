"""Integration adapters (takeoff prompt section 8).

Two families, kept in separate subpackages because they pull in opposite
directions and share nothing but the word "adapter":

  - ``sources/`` — INBOUND regulation documents (LocalFileAdapter and the
    NCA/Istitlaa/UQN portal stubs). Not built yet; M2's ``app/ingest.py``
    currently takes a ``--file`` path directly.
  - ``org/``     — INBOUND organization data (the graph M4's impact
    traversal walks): the demo YAML, the NCA self-assessment spreadsheet,
    Odoo, and the SAP/Oracle ERP stubs.
"""
