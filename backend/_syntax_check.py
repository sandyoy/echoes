import ast, sys
for f in ["permissions.py", "models.py", "collect_api.py"]:
    try:
        ast.parse(open(f).read())
        print(f, "syntax OK")
    except SyntaxError as e:
        print(f, "SYNTAX ERROR:", e)
        sys.exit(1)
