"""ruida-pa driver plugin for MeerK40t.

A new device driver that controls Ruida controllers through the GlueScript
API from the external ``ruida-pa`` package (``RdDriver`` in-process /
``RpcRdDriver`` over RPyC) instead of the raw Ruida protocol encoder used by
the legacy ``meerk40t.ruida`` driver.
"""
