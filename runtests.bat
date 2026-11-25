@echo off
cd /d C:\CertDesk
.venv\Scripts\python.exe manage.py test > out.txt 2>&1
echo EXIT_CODE=%ERRORLEVEL% >> out.txt
