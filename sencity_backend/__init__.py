import os
if os.getenv("DJANGO_DB", "sqlite") != "sqlite":
    import pymysql
    pymysql.install_as_MySQLdb()
