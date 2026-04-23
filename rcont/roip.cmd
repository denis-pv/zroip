@echo off
echo.
echox -c 0E "Server R0:"
py c:\python\rcont.py 192.168.0.1 1221 LIST
echo.
echox -c 0E "Server DOK:"
py c:\python\rcont.py 192.168.0.1 1222 LIST
echo.
echox -c 0E "Server SAT:"
py c:\python\rcont.py 192.168.0.1 1223 LIST