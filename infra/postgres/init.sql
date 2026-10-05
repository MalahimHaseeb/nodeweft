CREATE USER auth_user WITH PASSWORD 'auth_pass';
CREATE DATABASE auth_db OWNER auth_user;
CREATE USER execution_user WITH PASSWORD 'execution_pass';
CREATE DATABASE execution_db OWNER execution_user;
