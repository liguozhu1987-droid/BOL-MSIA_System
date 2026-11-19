import pyodbc
HOST = "IRSCNYTFINEREPORT.ap.inalfa.local"
for pwd in ["Inalfa@2026", "Inalfa@2026"]:
    try:
        c = pyodbc.connect(
            f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={HOST};"
            f"DATABASE=CMC;UID=sparePartRead;PWD={pwd};TrustServerCertificate=yes",
            timeout=10,
        )
        cur = c.cursor()
        cur.execute("SELECT @@SERVERNAME")
        print(f"PWD[{pwd}] -> OK server={cur.fetchone()[0]}")
        c.close()
    except Exception as e:
        print(f"PWD[{pwd}] -> FAIL: {str(e)[:70]}")
