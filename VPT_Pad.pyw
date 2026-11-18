# Запуск VPT | Pad з вихідників без чорного вікна консолі: подвійний клік у Провіднику
# (файли .pyw відкриває pythonw.exe). Закриття вікна програми ховає її в трей;
# повністю вийти — через значок у треї → "Вихід".
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
runpy.run_path(os.path.join(HERE, "main.py"), run_name="__main__")
