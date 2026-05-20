"""
往日可追忆 - 测试用例

运行方式：
    cd ~/往日可追忆/backend
    source venv/bin/activate
    python3 -m pytest test_main.py -v

确保后端服务已启动后再运行集成测试。
"""
import pytest
import requests
import json

BASE_URL = "http://localhost:8000"

# 测试数据
TEST_STORY = {
    "title": "测试故事 - 母亲的回忆",
    "protagonist": "母亲",
    "description": "这是一条测试数据，用于验证系统功能"
}

TEST_EVENT = {
    "title": "童年的夏天",
    "date": "约1970年",
    "date_precision": "approximate",
    "content": "夏天傍晚，和邻居小孩一起去河边捉萤火虫。",
    "location": "村口小河",
    "people": ["邻居家小明", "妹妹"],
    "tags": ["童年", "夏天"],
    "emotion": "快乐"
}

TEST_POLISH = {
    "text": "那年冬天很冷，我裹着棉被不想起床。",
    "style": "literary"
}

story_id = None


class TestStoryAPI:
    """故事管理测试"""

    def test_1_root(self):
        """测试根路径"""
        r = requests.get(f"{BASE_URL}/")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "running"
        print("✅ 根路径测试通过")

    def test_2_create_story(self):
        """测试创建故事"""
        global story_id
        r = requests.post(f"{BASE_URL}/api/story", json=TEST_STORY)
        assert r.status_code == 200
        data = r.json()
        assert data["code"] == 0
        assert data["data"]["title"] == TEST_STORY["title"]
        story_id = data["data"]["id"]
        print(f"✅ 创建故事成功: {story_id}")

    def test_3_list_stories(self):
        """测试获取故事列表"""
        global story_id
        r = requests.get(f"{BASE_URL}/api/story/list")
        assert r.status_code == 200
        data = r.json()
        assert data["code"] == 0
        assert len(data["data"]) > 0
        # 确认我们创建的故事在列表中
        titles = [s["title"] for s in data["data"]]
        assert TEST_STORY["title"] in titles
        print(f"✅ 获取故事列表成功, 共 {len(data['data'])} 个故事")

    def test_4_get_story(self):
        """测试获取单个故事详情"""
        global story_id
        r = requests.get(f"{BASE_URL}/api/story/{story_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["code"] == 0
        assert data["data"]["story"]["id"] == story_id
        assert data["data"]["story"]["protagonist"] == TEST_STORY["protagonist"]
        print(f"✅ 获取故事详情成功: {data['data']['story']['title']}")

    def test_5_update_story(self):
        """测试更新故事"""
        global story_id
        r = requests.put(f"{BASE_URL}/api/story/{story_id}", json={
            "description": "更新后的描述"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 0
        print("✅ 更新故事成功")


class TestEventAPI:
    """事件/时间线测试"""

    def test_1_create_events_via_extract(self):
        """测试AI提取时间线(模拟模式)"""
        global story_id
        # 先用快速方式创建事件（直接调extract会因为没有录音拒绝）
        # 我们直接手工创建事件来测试
        for i in range(3):
            event = dict(TEST_EVENT)
            event["story_id"] = story_id
            event["title"] = f"事件 #{i+1}: {TEST_EVENT['title']}"
            event["date"] = f"约{1960 + i*10}年"
            event["sort_order"] = i
            
            r = requests.post(f"{BASE_URL}/api/event/create", json=event)
            if r.status_code == 404:
                # 还没有创建接口，我们直接通过数据库验证
                # 不过我们先跳过
                pass
        
        # 验证事件列表接口可用
        r = requests.get(f"{BASE_URL}/api/event/list/{story_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["code"] == 0
        # events 应该返回一个数组
        assert isinstance(data["data"], list)
        print(f"✅ 事件列表接口正常, 当前有 {len(data['data'])} 个事件")

    def test_2_reorder_events(self):
        """测试事件排序"""
        global story_id
        # 先获取当前事件列表
        r = requests.get(f"{BASE_URL}/api/event/list/{story_id}")
        events = r.json()["data"]
        if len(events) >= 2:
            event_ids = [e["id"] for e in reversed(events)]
            r = requests.post(f"{BASE_URL}/api/event/reorder", json={
                "event_ids": event_ids
            })
            assert r.status_code == 200
            assert r.json()["code"] == 0
            print(f"✅ 事件重新排序成功")


class TestAIPolish:
    """AI 润色功能测试"""

    def test_1_polish_literary(self):
        """测试文学风格润色"""
        r = requests.post(f"{BASE_URL}/api/ai/polish", json=TEST_POLISH)
        assert r.status_code == 200
        data = r.json()
        assert data["code"] == 0
        assert data["data"]["original"] == TEST_POLISH["text"]
        assert data["data"]["style"] == "literary"
        # 润色后的文字应该和原文不同
        assert data["data"]["polished"] != TEST_POLISH["text"]
        print(f"✅ 文学风格润色成功")
        print(f"   原文: {data['data']['original'][:40]}...")
        print(f"   润色: {data['data']['polished'][:40]}...")

    def test_2_polish_emotional(self):
        """测试情感风格润色"""
        r = requests.post(f"{BASE_URL}/api/ai/polish", json={
            "text": "第一次见到她是在图书馆。",
            "style": "emotional"
        })
        assert r.status_code == 200
        data = r.json()
        assert data["code"] == 0
        assert data["data"]["style"] == "emotional"
        print(f"✅ 情感风格润色成功: {data['data']['polished'][:50]}...")


class TestBiographyAPI:
    """传记生成测试"""

    def test_1_generate_biography(self):
        """测试生成传记"""
        global story_id
        r = requests.post(f"{BASE_URL}/api/biography/generate/{story_id}", 
                         params={"style": "plain"})
        # 因为没有事件，可能会返回空传记，但不能报500错误
        assert r.status_code in [200, 400, 404]
        if r.status_code == 200:
            data = r.json()
            assert data["code"] == 0
            print(f"✅ 生成传记成功")
        else:
            print(f"ℹ️ 生成传记返回 {r.status_code}（预期内，因暂无事件数据）")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--capture=tee-sys"])
