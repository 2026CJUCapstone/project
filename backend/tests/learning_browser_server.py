"""Isolated learning E2E fixture, port 18002. Real API/queue; FAKE compiler.

Never imports production data. Every invocation uses a new temporary SQLite DB.
Run from backend: python tests/learning_browser_server.py
"""
import os
os.environ['BPP_TEST_ORIGIN'] = 'http://127.0.0.1:4176'
from contest_browser_server import app, SessionLocal
from app.models.database import Problem, User

with SessionLocal() as db:
    admin = db.query(User).filter_by(username='contest_admin').one()
    for i, difficulty in enumerate(['iron5', 'iron4', 'iron3', 'bronze5']):
        db.add(Problem(id=f'learning-e2e-{i}', creator_id=admin.id,
            title=f'학습 테스트 문제 {i + 1}', difficulty=difficulty,
            tags=['io'] if i < 3 else ['array'], points=100,
            description='로컬 UI·API 검증용 문제입니다. 이 환경의 실행기는 실제 컴파일러가 아닌 테스트 대역입니다.',
            test_cases={'sample': [{'input': '42', 'expected_output': '42'}],
                        'hidden': [{'input': '42', 'expected_output': '42'}]}))
    db.commit()

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=18002)
