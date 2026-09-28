CREATE DATABASE IF NOT EXISTS my_db_info;
USE my_db_info;

-- table with user credentials
CREATE TABLE IF NOT EXISTS user_info (
    username_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    user_password VARCHAR(255) NOT NULL
);

-- table for server session tokens
-- session id is used as a session token
CREATE TABLE IF NOT EXISTS session_info (
    session_id VARCHAR(255) PRIMARY KEY, 
    user_id INT NOT NULL,
    time_created DATETIME DEFAULT CURRENT_TIMESTAMP,
    time_expiration DATETIME NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(session_id) ON DELETE CASCADE
);

-- table to hold records information
CREATE TABLE IF NOT EXISTS record_info (
    id INT AUTO_INCREMENT PRIMARY KEY,
    primary_field VARCHAR(255) NOT NULL,
    secondary_field TEXT NOT NULL
);