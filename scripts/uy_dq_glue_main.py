"""The script Glue runs for the UY silver gate (UY-043.4): s3://<code bucket>/uy/dq/.

A Spark job's ``script_location`` has to be a single .py file. Everything it does lives in
``sorteos.uy.dq.glue_job``, which arrives installed from the zip of wheels
(``--additional-python-modules``, UY-026.2) and is covered by the unit tests.
"""

from sorteos.uy.dq.glue_job import main

main()
