CREATE TABLE IF NOT EXISTS comment_info (
    id INT AUTO_INCREMENT PRIMARY KEY,
    record_id INT NOT NULL,
    comment_text VARCHAR(255) NOT NULL,
    FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE CASCADE
);