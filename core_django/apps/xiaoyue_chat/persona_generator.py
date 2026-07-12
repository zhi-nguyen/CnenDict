import random

NAMES_POOL = {
    "wuxia": {
        "zh": [
            "小月", "雪儿", "梦瑶", "灵儿", "雨彤", "诗婷", "若兰", "芷若", "婉婷", "紫嫣",
            "冰凝", "慕晴", "雅芝", "秀娟", "秋水", "凌霜", "碧瑶", "云裳", "素心", "清荷",
            "映雪", "飞鸢", "晓霜", "蝶舞", "凤铃", "兰溪", "月影", "寒烟", "翠微", "沐风",
            "含烟", "听雨", "霓裳", "琉璃", "锦瑟", "瑶琴", "飘雪", "凝香", "玲珑", "青萝",
            "暮烟", "丹青", "落霞", "明珠", "幻蝶"
        ],
        "en": [
            "Xiaoyue", "Xue'er", "Mengyao", "Ling'er", "Yutong", "Shiting", "Ruolan", "Zhiruo",
            "Wanting", "Ziyan", "Bingning", "Muqing", "Yazhi", "Xiujuan", "Qiushui", "Lingshuang",
            "Biyao", "Yunshang", "Suxin", "Qinghe", "Yingxue", "Feiyuan", "Xiaoshuang", "Diewu",
            "Fengling", "Lanxi", "Yueying", "Hanyan", "Cuiwei", "Mufeng", "Hanyan", "Tingyu",
            "Nichang", "Liuli", "Jinse", "Yaoqin", "Piaoxue", "Ningxiang", "Linglong", "Qingluo",
            "Muyan", "Danqing", "Luoxia", "Mingzhu", "Huandie"
        ]
    },
    "modern": {
        "zh": [
            "薇薇", "思琪", "小云", "雨娇", "美玲", "欣怡", "静雯", "雅琳", "晓婷", "佩姗",
            "慧敏", "佳颖", "丽芳", "雪梅", "梦凡", "雨晴", "心怡", "若萱", "诗涵", "子萱",
            "可馨", "梓涵", "雨桐", "语嫣", "紫萱", "筱筱", "婉如", "琳琳", "思韵", "悦然",
            "芷柔", "梦洁", "雅琪", "小蝶", "诗雨", "安琪", "嘉怡", "文静", "亦菲", "瑞雪"
        ],
        "en": [
            "Sarah", "Emily", "Chloe", "Jessica", "Grace", "Olivia", "Sophia", "Isabella",
            "Emma", "Ava", "Lily", "Mia", "Zoe", "Amelia", "Charlotte", "Harper", "Ella",
            "Aria", "Scarlett", "Luna", "Penelope", "Layla", "Riley", "Nora", "Hazel",
            "Aurora", "Savannah", "Audrey", "Claire", "Stella", "Natalie", "Violet", "Hannah",
            "Leah", "Lucy", "Eleanor", "Maya", "Paisley", "Evelyn", "Willow"
        ]
    },
    "academic": {
        "zh": {
            "professor": [
                "李教授", "陈教授", "张教授", "林教授", "王教授", "刘教授",
                "赵教授", "黄教授", "周教授", "吴教授", "孙教授", "郑教授",
                "马教授", "朱教授", "胡教授", "何教授", "沈教授", "曾教授"
            ],
            "classmate": [
                "薇薇", "雨娇", "小云", "思琪", "欣怡", "佳琪", "小雨", "雪怡", "静秋",
                "心语", "若曦", "梓萱", "诗韵", "雅婷", "芷晴", "悦心", "梦琪", "语桐",
                "可欣", "灵犀", "书瑶", "芳菲", "晓晨", "念慈"
            ]
        },
        "en": {
            "professor": [
                "Professor Helen", "Professor Vance", "Professor Emily", "Professor Grace",
                "Professor Charlotte", "Professor Sarah", "Professor Diana", "Professor Margaret",
                "Professor Catherine", "Professor Victoria", "Professor Eleanor", "Professor Audrey",
                "Professor Irene", "Professor Sylvia", "Professor Beatrice", "Professor Rosalind"
            ],
            "classmate": [
                "Jane", "Emily", "Chloe", "Sarah", "Grace", "Olivia", "Lily", "Ava",
                "Rachel", "Monica", "Phoebe", "Alice", "Diana", "Julia", "Clara", "Iris",
                "Fiona", "Vera", "Nina", "Tessa"
            ]
        }
    }
}

PERSONALITY_PROFILES = [
    {
        "type": "cold",
        "desc": "Lạnh lùng, trầm tính, ít nói, nghiêm túc và giữ khoảng cách nhất định.",
        "avatar_emoji": "❄️",
        "joy_sensitivity": 0.3,
        "joy_decay_rate": 0.7,
        "sad_sensitivity": 1.2,
        "sad_decay_rate": 0.3
    },
    {
        "type": "cheerful",
        "desc": "Vui vẻ, tăng động, tràn đầy năng lượng, thân thiện và nhiều năng lượng tích cực.",
        "avatar_emoji": "☀️",
        "joy_sensitivity": 1.5,
        "joy_decay_rate": 0.2,
        "sad_sensitivity": 0.4,
        "sad_decay_rate": 0.8
    },
    {
        "type": "strict",
        "desc": "Nghiêm khắc, kỷ luật, coi trọng tính chính xác và sửa lỗi sai bài tập rất kỹ lưỡng.",
        "avatar_emoji": "📐",
        "joy_sensitivity": 0.4,
        "joy_decay_rate": 0.6,
        "sad_sensitivity": 1.4,
        "sad_decay_rate": 0.4
    },
    {
        "type": "gentle",
        "desc": "Dịu dàng, ôn hòa, kiên nhẫn giảng giải, bao dung và luôn động viên đối phương học tập.",
        "avatar_emoji": "🌸",
        "joy_sensitivity": 1.0,
        "joy_decay_rate": 0.4,
        "sad_sensitivity": 0.5,
        "sad_decay_rate": 0.6
    }
]

def generate_random_persona(user_name: str, gender: str, birth_year: int, context_setting: str, learning_language: str, user_level: str, relation_choice: str = None) -> dict:
    # 1. Determine Relationship Type / Subtype
    relation_type = "default"
    is_professor = False
    
    # Normalize relation choice
    rel_choice = str(relation_choice).lower().strip() if relation_choice else "peer"
    
    if context_setting == "academic":
        if rel_choice == "professor":
            relation_type = "professor"
            is_professor = True
        elif rel_choice == "classmate":
            relation_type = "classmate"
        else:
            # Default or "peer" -> classmate
            relation_type = "classmate"
            
    elif context_setting == "modern":
        if rel_choice in ["colleague", "bestie", "crush", "interviewer"]:
            relation_type = rel_choice
        elif rel_choice == "peer":
            # Randomize peer relationships except crush!
            relation_type = random.choice(["colleague", "bestie"])
        else:
            relation_type = random.choice(["colleague", "bestie"])
            
    elif context_setting == "wuxia":
        if rel_choice == "master":
            relation_type = "master"
        else:
            relation_type = "peer"

    # 2. Select or Customize Personality Profile
    if relation_type == "master":
        # Female Master has 2 personalities: Cold/Aloof ("Lạnh lùng") and Approachable/Gentle ("Dễ gần")
        # both having strict boundaries/limits.
        chosen_type = random.choice(["cold", "gentle"])
        if chosen_type == "cold":
            personality = {
                "type": "cold",
                "desc": "Lạnh lùng, tôn nghiêm, trầm tính, nghiêm túc và luôn giữ khoảng cách sư đồ tôn kính.",
                "avatar_emoji": "❄️",
                "joy_sensitivity": 0.3,
                "joy_decay_rate": 0.7,
                "sad_sensitivity": 1.2,
                "sad_decay_rate": 0.3
            }
        else:
            personality = {
                "type": "gentle",
                "desc": "Dịu dàng, ôn hòa, kiên nhẫn dạy bảo, dễ gần nhưng luôn giữ giới hạn và tôn ti trật tự nhất định.",
                "avatar_emoji": "🌸",
                "joy_sensitivity": 1.0,
                "joy_decay_rate": 0.4,
                "sad_sensitivity": 0.5,
                "sad_decay_rate": 0.6
            }
    else:
        # Standard random personality
        personality = random.choice(PERSONALITY_PROFILES)

    # 3. Random Name
    name_lang = learning_language if learning_language in ["zh", "en"] else "zh"
    if context_setting == "academic":
        agent_name = random.choice(NAMES_POOL["academic"][name_lang][relation_type])
    elif context_setting == "wuxia" and relation_type == "master":
        # Wuxia master specific names - default to append "仙子" or "圣女"
        master_bases = {
            "zh": [
                "玉清", "缈然", "静虚", "瑶华", "紫霄", "太寒", "广寒", "清漪",
                "素灵", "凌云", "碧落", "瑶池", "玄霜", "紫微", "青鸾", "霜华",
                "天瑶", "云梦", "月华", "星河", "凤仪", "莲心", "冰魄", "寒玉"
            ],
            "en": [
                "Yuqing", "Miaoran", "Jingxu", "Yaohua", "Zixiao", "Taihan", "Guanghan", "Qingyi",
                "Suling", "Lingyun", "Biluo", "Yaochi", "Xuanshuang", "Ziwei", "Qingluan", "Shuanghua",
                "Tianyao", "Yunmeng", "Yuehua", "Xinghe", "Fengyi", "Lianxin", "Bingpo", "Hanyu"
            ]
        }
        base_name = random.choice(master_bases[name_lang])
        if name_lang == "zh":
            suffix = random.choice(["仙子", "圣女"])
            agent_name = base_name + suffix
        else:
            prefix = random.choice(["Fairy", "Saintess"])
            agent_name = f"{prefix} {base_name}"
    else:
        agent_name = random.choice(NAMES_POOL[context_setting][name_lang])
        # Wuxia peer roles - randomly append "仙子" or "Saintess/Fairy" (e.g., 25% chance)
        if context_setting == "wuxia" and random.random() < 0.25:
            if name_lang == "zh":
                suffix = random.choice(["仙子", "圣女"])
                agent_name = agent_name + suffix
            else:
                prefix = random.choice(["Fairy", "Saintess"])
                agent_name = f"{prefix} {agent_name}"
        
    # 4. Random Birth Year
    is_older_role = (
        (context_setting == "academic" and is_professor) or 
        (context_setting == "modern" and relation_type == "interviewer") or
        (context_setting == "wuxia" and relation_type == "master")
    )
    
    if is_older_role:
        # Superior roles: age is mysterious/unknown
        agent_birth_year = None
    else:
        # Peer roles: biased toward agent being OLDER than the user
        # ~60% chance older (1-5 years), ~25% same age, ~15% younger (1-3 years)
        roll = random.random()
        if roll < 0.60:
            # Agent is older (born earlier = smaller birth year)
            agent_birth_year = birth_year - random.randint(1, 5)
        elif roll < 0.85:
            # Same age
            agent_birth_year = birth_year
        else:
            # Agent is younger
            agent_birth_year = birth_year + random.randint(1, 3)
        
    age_diff = None if agent_birth_year is None else birth_year - agent_birth_year
    
    # 5. Determine Honorifics / Addressing
    user_honorific = ""
    agent_self_ref = ""
    
    if context_setting == "wuxia":
        if relation_type == "master":
            user_honorific = "徒儿"
            agent_self_ref = "为师"
        elif age_diff < 0:
            user_honorific = "师兄" if gender == "male" else "师姐"
            agent_self_ref = "妹妹"
        elif age_diff > 0:
            user_honorific = "师弟" if gender == "male" else "师妹"
            agent_self_ref = "姐姐"
        else:
            user_honorific = "同门"
            agent_self_ref = "妹妹"
            
    elif context_setting == "modern":
        if relation_type == "interviewer":
            user_honorific = "Em"
            agent_self_ref = "Tôi"
        else:
            if age_diff < 0:
                user_honorific = "Anh" if gender == "male" else "Chị"
                agent_self_ref = "Em"
            elif age_diff > 0:
                user_honorific = "Em"
                agent_self_ref = "Chị"
            else:
                user_honorific = "Bạn"
                agent_self_ref = "Mình"
            
    elif context_setting == "academic":
        if is_professor:
            user_honorific = "Em"
            agent_self_ref = "Cô"
        else:
            # Classmate
            if age_diff < 0:
                user_honorific = "Anh" if gender == "male" else "Chị"
                agent_self_ref = "Em"
            elif age_diff > 0:
                user_honorific = "Em"
                agent_self_ref = "Chị"
            else:
                user_honorific = "Bạn"
                agent_self_ref = "Mình"

    return {
        "user_name": user_name,
        "user_gender": gender,
        "user_birth_year": birth_year,
        "agent_name": agent_name,
        "agent_birth_year": agent_birth_year,
        "personality_type": personality["type"],
        "personality_desc": personality["desc"],
        "avatar_emoji": personality["avatar_emoji"],
        "context_setting": context_setting,
        "learning_language": learning_language,
        "user_level": user_level,
        "age_diff": age_diff,
        "user_honorific": user_honorific,
        "agent_self_ref": agent_self_ref,
        "relation_type": relation_type,
        "joy_sensitivity": personality["joy_sensitivity"],
        "joy_decay_rate": personality["joy_decay_rate"],
        "sad_sensitivity": personality["sad_sensitivity"],
        "sad_decay_rate": personality["sad_decay_rate"]
    }
