from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

eng = create_engine("sqlite:///:memory:", poolclass=QueuePool, pool_size=2, max_overflow=0)
Sm = sessionmaker(eng, expire_on_commit=False)

with Sm() as s:
    s.execute(text("SELECT 1"))
    print("After execute, before commit:", eng.pool.status())
    s.commit()
    print("After commit:", eng.pool.status())
    import time; time.sleep(0.05)
    print("After sleep (no DB activity):", eng.pool.status())
    s.execute(text("SELECT 1"))
    print("After 2nd execute:", eng.pool.status())
print("After session close:", eng.pool.status())
