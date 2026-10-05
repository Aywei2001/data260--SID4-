import random
import time
from sqlalchemy.orm import Session
from hw3_authentication import SessionLocal, Record, Base, engine
from sqlalchemy import Column, Integer, String, ForeignKey
import numpy as np

class Comment(Base):
    __tablename__ = "comment_info"
    id = Column(Integer, primary_key=True, index=True)
    record_id = Column(Integer, ForeignKey("records.id"))
    comment_text = Column(String(255))

Base.metadata.create_all(bind=engine)

def seed_data():
    #set seed based on assigend seed value
    my_seed = 1339
    random.seed(my_seed)

    db: Session = SessionLocal()

    #clear any data that already exists
    db.query(Comment).delete()
    db.query(Record).delete()
    db.commit()

    #seed the 5000 records
    records = [Record(primary_field=f"record: {i}", secondary_field=f"description: {i}") for i in range(1, 5001)]
    db.bulk_save_objects(records)
    db.commit()

    #get all existing id records
    all_record_ids = [r.id for r in db.query(Record.id).all()]

    #seed 200 related rows 
    comments = []
    for i in range(1, 201):
        rec_id = random.choice(all_record_ids)
        comments.append(
            Comment(record_id=rec_id, comment_text=f"sample: {i}")
        )
    db.bulk_save_objects(comments)
    db.commit()
    db.close()
    print("seeding complete")

def get_benchmarks():
    page_size = [10, 50, 200]
    total_versions = ["naive", "fixed"]
    n_requests = 30

    def run_benchmark():
        print(f"| Page size | Version | SQL stmts/req | p50 (ms) | p95 (ms) | p99 (ms) |")

        for size in page_size:
            for version in total_versions:
                latencies = []
                
                # Count expected SQL statements
                sql_stmts = (1 + size) if version == "naive" else 1

                for _ in range(n_requests):
                    start_time = time.perf_counter()
                    res = requests.get(f"{base_url}/{version}?limit={size}")
                    end_time = time.perf_counter()

                    if res.status_code == 200:
                        latencies.append((end_time - start_time) * 1000)

                p50 = np.percentile(latencies, 50)
                p95 = np.percentile(latencies, 95)
                p99 = np.percentile(latencies, 99)

                print(f"| {size} | {version} | {sql_stmts} | {p50:.2f} | {p95:.2f} | {p99:.2f} |")

if __name__ == "__main__":
    seed_data()
    get_benchmarks()