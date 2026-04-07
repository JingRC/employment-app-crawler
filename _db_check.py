import sqlite3
conn = sqlite3.connect("就业App原型/backend_api/data/jobs.db")
print("Total:", conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])
print("With salary:", conn.execute("SELECT COUNT(*) FROM jobs WHERE salary_text != '' AND salary_text IS NOT NULL").fetchone()[0])
for r in conn.execute("SELECT city_name, COUNT(*) as c FROM jobs GROUP BY city_name ORDER BY c DESC").fetchall():
    print(f"  {r[0] or '(empty)'}: {r[1]}")
conn.close()
