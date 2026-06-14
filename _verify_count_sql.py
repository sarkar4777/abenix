import sys
sys.path.insert(0, 'packages/db')
sys.path.insert(0, 'apps/api')
from sqlalchemy import select, func
from models.knowledge_base import KnowledgeBase

count_base = select(KnowledgeBase).where(KnowledgeBase.tenant_id == None)
bad = select(func.count()).select_from(count_base.subquery())
print('=== BAD (current) ===')
print(str(bad.compile()))
print()
good = select(func.count(KnowledgeBase.id)).where(KnowledgeBase.tenant_id == None)
print('=== GOOD (fix) ===')
print(str(good.compile()))
