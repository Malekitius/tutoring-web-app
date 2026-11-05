\getenv password TUTOR_DB_PASSWORD
CREATE ROLE tutor LOGIN PASSWORD :'password';
ALTER DATABASE tutor OWNER TO tutor;
