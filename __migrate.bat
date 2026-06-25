@echo off
docker exec mytrack-web-1 python manage.py migrate mytrack_compliance > C:\Users\thaba\migrate_out.txt 2>&1
