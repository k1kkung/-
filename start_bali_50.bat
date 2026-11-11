@echo off
setlocal

set "SOUP_AI_STORIES_FILE=%~dp0backend\stories_bali_50.json"
set "SOUP_AI_DB_FILE=%~dp0backend\stories_bali_50.db"

call "%~dp0start.bat"

endlocal
