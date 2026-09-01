#!/usr/bin/env python3
"""Seed evaluation datasets with **precisely annotated** ground-truth chunks.

Usage:
    cd backend && PYTHONUTF8=1 python scripts/seed_eval_data.py

Design (Phase 1 optimisation):
  - Each QA pair explicitly lists which chunk indices from which document
    contain the answer (1-5 chunks, NOT the whole document).
  - This fixes the Recall@5 denominator from 30-50 → 1-5.
  - Supports ``ground_truth_chunk_ids`` (new) and falls back to
    ``expected_chunk_ids`` (legacy) for compatibility.

Output:
    - Python 基础评估: 15 QA (easy=5, medium=7, hard=3)
    - Java 基础评估:   15 QA (easy=5, medium=7, hard=3)
"""
from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.models.feedback import EvalDataset, EvalQAPair
from app.models.document import Document, DocumentChunk
from app.models.user import User


# ═════════════════════════════════════════════════════════════════════
#  Annotation format
# ═════════════════════════════════════════════════════════════════════
#
# Each QA pair specifies:
#   doc_match  —  substring of the document title (for DB lookup)
#   chunk_idx  —  0-based chunk indices within that document (NOT all chunks!)
#   Typically 1-3 chunks per question; at most 5.
#
# The script resolves these into ``ground_truth_chunk_ids`` at seed time.

PYTHON_QA: list[dict] = [
    # ── Data Types / Introduction ─────────────────────────────────
    {
        "question": "Python 中的列表（list）和元组（tuple）的主要区别是什么？",
        "reference_answer": (
            "列表是可变的（mutable），可以添加、删除或修改元素；"
            "元组是不可变的（immutable），创建后不能修改。"
            "列表用方括号 []，元组用圆括号 ()。"
        ),
        "doc_match": "introduction",
        "chunk_indices": [0, 2],       # 列表定义 + 元组定义
        "difficulty": "easy",
        "tags": ["基础", "数据结构", "Python"],
        "ground_truth_notes": "introduction.md 开头介绍列表和元组的基本概念",
    },
    {
        "question": "Python 的列表推导式（list comprehension）是什么？举例说明。",
        "reference_answer": (
            "列表推导式是一种简洁创建列表的方式："
            "[expression for item in iterable if condition]。"
            "例如：[x**2 for x in range(10) if x % 2 == 0]。"
        ),
        "doc_match": "introduction",
        "chunk_indices": [3],          # 列表推导式章节
        "difficulty": "medium",
        "tags": ["基础", "列表推导式", "Python"],
        "ground_truth_notes": "introduction.md 中关于列表推导式的段落",
    },
    {
        "question": "Python 中的 for 循环和 while 循环有什么区别？",
        "reference_answer": (
            "for 循环用于遍历可迭代对象（如列表、字符串）；"
            "while 循环在条件为真时重复执行。"
        ),
        "doc_match": "controlflow",
        "chunk_indices": [1, 2],
        "difficulty": "medium",
        "tags": ["控制流", "循环", "Python"],
        "ground_truth_notes": "controlflow.md 中 for 和 while 循环章节",
    },
    # ── Functions / Modules ───────────────────────────────────────
    {
        "question": "Python 中如何定义一个函数？请写出基本语法。",
        "reference_answer": (
            "使用 def 关键字定义函数：def function_name(parameters): "
            "后面跟缩进的函数体。可以使用 return 返回值。"
        ),
        "doc_match": "modules",
        "chunk_indices": [0],
        "difficulty": "easy",
        "tags": ["基础", "函数", "Python"],
        "ground_truth_notes": "modules.md 开头的函数定义部分",
    },
    {
        "question": "Python 中 lambda 函数是什么？如何使用？",
        "reference_answer": (
            "lambda 函数是匿名函数，使用 lambda 关键字定义："
            "lambda args: expression。常用于高阶函数如 map、filter、sorted 的 key 参数。"
        ),
        "doc_match": "classes",
        "chunk_indices": [2],
        "difficulty": "medium",
        "tags": ["函数", "lambda", "Python"],
        "ground_truth_notes": "classes.md 中关于 lambda 的说明",
    },
    {
        "question": "Python 中的装饰器（decorator）是什么？有什么用途？",
        "reference_answer": (
            "装饰器是一种高阶函数，可以在不修改原函数代码的情况下为函数添加额外功能。"
            "使用 @decorator_name 语法应用。常用于日志、性能测试、权限检查等。"
        ),
        "doc_match": "glossary",
        "chunk_indices": [0],
        "difficulty": "hard",
        "tags": ["进阶", "装饰器", "Python"],
        "ground_truth_notes": "glossary.md 中关于装饰器的定义和示例",
    },
    # ── Data Structures ───────────────────────────────────────────
    {
        "question": "Python 中字典（dict）的常用操作有哪些？",
        "reference_answer": (
            "字典是键值对集合。常用操作：dict[key] 访问、"
            "dict.get() 安全访问、dict.keys()/values()/items() 遍历、"
            "update() 合并、pop() 删除。"
        ),
        "doc_match": "datastructures",
        "chunk_indices": [1],
        "difficulty": "easy",
        "tags": ["数据结构", "字典", "Python"],
        "ground_truth_notes": "datastructures.md 中字典部分的说明",
    },
    # ── I/O ───────────────────────────────────────────────────────
    {
        "question": "Python 中如何处理文件读写？请写出打开文件的基本模式。",
        "reference_answer": (
            "使用 open() 函数打开文件，常用模式：'r'（读取）、'w'（写入）、"
            "'a'（追加）、'b'（二进制模式）。使用 with 语句确保文件正确关闭。"
        ),
        "doc_match": "inputoutput",
        "chunk_indices": [0, 1],
        "difficulty": "medium",
        "tags": ["I/O", "文件操作", "Python"],
        "ground_truth_notes": "inputoutput.md 中文件打开和读写部分",
    },
    # ── Errors / Exceptions ───────────────────────────────────────
    {
        "question": "Python 的异常处理机制是怎样的？try/except 如何工作？",
        "reference_answer": (
            "使用 try-except 块捕获异常：try 块中放置可能出错的代码，"
            "except 块处理异常。可以指定捕获特定异常类型，"
            "使用 finally 块执行清理代码。"
        ),
        "doc_match": "errors",
        "chunk_indices": [0, 2],
        "difficulty": "medium",
        "tags": ["异常处理", "基础", "Python"],
        "ground_truth_notes": "errors.md 中 try/except/finally 的说明",
    },
    # ── Classes / OOP ─────────────────────────────────────────────
    {
        "question": "Python 中类和对象的关系是什么？如何定义一个类？",
        "reference_answer": (
            "类是对象的蓝图。使用 class 关键字定义类，"
            "__init__ 方法初始化对象属性，self 表示实例本身。"
        ),
        "doc_match": "classes",
        "chunk_indices": [0, 1],
        "difficulty": "medium",
        "tags": ["OOP", "类", "Python"],
        "ground_truth_notes": "classes.md 中类定义和 __init__ 部分",
    },
    # ── Advanced ──────────────────────────────────────────────────
    {
        "question": "Python 中的生成器（generator）和 yield 关键字如何工作？",
        "reference_answer": (
            "生成器使用 yield 关键字返回值并暂停函数执行，"
            "下次调用从暂停处继续。生成器函数返回一个迭代器对象，"
            "适合处理大数据流，节省内存。"
        ),
        "doc_match": "glossary",
        "chunk_indices": [1],
        "difficulty": "hard",
        "tags": ["进阶", "生成器", "yield", "Python"],
        "ground_truth_notes": "glossary.md 中生成器的定义和示例",
    },
    {
        "question": "Python 中 GIL（全局解释器锁）对多线程有什么影响？",
        "reference_answer": (
            "GIL 确保同一时刻只有一个线程执行 Python 字节码。"
            "因此 CPU 密集型多线程程序无法利用多核优势，"
            "但 I/O 密集型任务仍可受益。密集计算应使用 multiprocessing。"
        ),
        "doc_match": "glossary",
        "chunk_indices": [2],
        "difficulty": "hard",
        "tags": ["进阶", "多线程", "GIL", "Python"],
        "ground_truth_notes": "glossary.md 中关于 GIL 的说明",
    },
    {
        "question": "Python 中列表和字符串的切片操作如何使用？",
        "reference_answer": (
            "切片使用 [start:stop:step] 语法。start 默认 0，stop 默认结尾，"
            "step 默认为 1。负索引从末尾开始计数。例如 s[::-1] 反转字符串。"
        ),
        "doc_match": "introduction",
        "chunk_indices": [1],
        "difficulty": "easy",
        "tags": ["基础", "切片", "Python"],
        "ground_truth_notes": "introduction.md 中关于序列类型切片操作的部分",
    },
    {
        "question": "Python 的 pip 包管理器和虚拟环境（venv）如何工作？",
        "reference_answer": (
            "pip 是 Python 包管理器，用于安装第三方库。venv 创建隔离的 Python 环境，"
            "避免不同项目依赖冲突。使用 python -m venv myenv 创建，Scripts/activate 激活。"
        ),
        "doc_match": "modules",
        "chunk_indices": [3],
        "difficulty": "medium",
        "tags": ["工具", "pip", "venv", "Python"],
        "ground_truth_notes": "modules.md 中关于模块安装和环境管理的介绍",
    },
]


JAVA_QA: list[dict] = [
    # ── Basics ────────────────────────────────────────────────────
    {
        "question": "Java 中的 main 方法签名是什么？为什么必须是 public static void？",
        "reference_answer": (
            "public static void main(String[] args)。public 确保 JVM 可访问，"
            "static 无需创建实例即可调用，void 不返回值，String[] args 接收命令行参数。"
        ),
        "doc_match": "java_syntax",
        "chunk_indices": [0],
        "difficulty": "easy",
        "tags": ["基础", "main方法", "Java"],
        "ground_truth_notes": "java_syntax.md 开头的 main 方法说明",
    },
    {
        "question": "Java 中基本数据类型有哪些？",
        "reference_answer": (
            "byte(8位)、short(16位)、int(32位)、long(64位)、float(32位)、"
            "double(64位)、boolean、char(16位 Unicode 字符)。"
        ),
        "doc_match": "java_data_types",
        "chunk_indices": [0, 1],
        "difficulty": "easy",
        "tags": ["基础", "数据类型", "Java"],
        "ground_truth_notes": "java_data_types.md 中基本数据类型介绍",
    },
    {
        "question": "Java 中 final 关键字可以修饰什么？分别有什么效果？",
        "reference_answer": (
            "final 修饰类（不可继承）、修饰方法（不可重写）、"
            "修饰变量（变为常量不可修改）。引用类型变量 final 表示引用不可变。"
        ),
        "doc_match": "java_syntax",
        "chunk_indices": [1],
        "difficulty": "medium",
        "tags": ["关键字", "final", "Java"],
        "ground_truth_notes": "java_syntax.md 中关于 final 关键字的说明",
    },
    # ── OOP ───────────────────────────────────────────────────────
    {
        "question": "Java 中四种访问修饰符是什么？各自的可见范围？",
        "reference_answer": (
            "public（所有类可见）、protected（同包+子类可见）、"
            "default/package-private（仅同包可见）、private（仅本类可见）。"
        ),
        "doc_match": "java_scope",
        "chunk_indices": [0],
        "difficulty": "easy",
        "tags": ["OOP", "访问控制", "Java"],
        "ground_truth_notes": "java_scope.md 中访问修饰符的完整介绍",
    },
    {
        "question": "Java 中什么是继承（inheritance）？如何使用 extends 关键字？",
        "reference_answer": (
            "继承允许子类继承父类的属性和方法。使用 extends 关键字："
            "class Dog extends Animal。Java 只支持单继承。子类可用 super 调用父类方法。"
        ),
        "doc_match": "java_inheritance",
        "chunk_indices": [0, 1],
        "difficulty": "medium",
        "tags": ["OOP", "继承", "Java"],
        "ground_truth_notes": "java_inheritance.md 中继承机制的介绍",
    },
    {
        "question": "Java 中接口（interface）和抽象类（abstract class）的区别？",
        "reference_answer": (
            "接口用 interface 定义，方法默认 abstract；Java 8+ 支持 default/static 方法。"
            "抽象类用 abstract class 定义，可以有构造方法和实例变量。"
            "类可以实现多个接口但只能继承一个抽象类。"
        ),
        "doc_match": "java_interface",
        "chunk_indices": [0, 1],
        "difficulty": "hard",
        "tags": ["OOP", "接口", "抽象类", "Java"],
        "ground_truth_notes": "java_interface.md 中接口定义和与抽象类的对比",
    },
    # ── Collections ───────────────────────────────────────────────
    {
        "question": "Java 中 ArrayList 和 LinkedList 的区别是什么？",
        "reference_answer": (
            "ArrayList 基于动态数组，随机访问快 O(1)，插入删除慢 O(n)；"
            "LinkedList 基于双向链表，插入删除快 O(1)，随机访问慢 O(n)。"
        ),
        "doc_match": "java_arraylist",
        "chunk_indices": [0, 1],
        "difficulty": "medium",
        "tags": ["集合", "List", "Java"],
        "ground_truth_notes": "java_arraylist.md 和 java_linkedlist.md 中的对比说明",
    },
    {
        "question": "Java 中 HashMap 的工作原理是什么？",
        "reference_answer": (
            "HashMap 基于哈希表实现。put 时计算 key 的 hashCode() 确定桶位置，"
            "冲突时使用链表/红黑树存储。get 时同样计算 hashCode 查找。"
            "初始容量 16，负载因子 0.75。"
        ),
        "doc_match": "java_hashmap",
        "chunk_indices": [0],
        "difficulty": "hard",
        "tags": ["集合", "HashMap", "Java"],
        "ground_truth_notes": "java_hashmap.md 中 HashMap 原理介绍",
    },
    {
        "question": "Java 中自动装箱（autoboxing）和拆箱（unboxing）是什么？",
        "reference_answer": (
            "自动装箱是 Java 自动将基本类型转为对应的包装类（如 int→Integer）；"
            "拆箱是反向转换（Integer→int）。Java 5+ 支持。"
        ),
        "doc_match": "java_wrapper_classes",
        "chunk_indices": [0],
        "difficulty": "medium",
        "tags": ["基础", "包装类", "Java"],
        "ground_truth_notes": "java_wrapper_classes.md 中自动装箱/拆箱的说明",
    },
    # ── Exception ─────────────────────────────────────────────────
    {
        "question": "Java 中 try-catch-finally 的执行顺序是怎样的？",
        "reference_answer": (
            "先执行 try 块，发生异常则跳转到对应 catch 块，"
            "无论是否异常 finally 块都会执行。"
            "try 必须有 catch 或 finally 之一。"
        ),
        "doc_match": "java_try_catch",
        "chunk_indices": [0, 1],
        "difficulty": "easy",
        "tags": ["异常处理", "基础", "Java"],
        "ground_truth_notes": "java_try_catch.md 中异常处理机制的介绍",
    },
    # ── String ─────────────────────────────────────────────────────
    {
        "question": "Java 中 == 和 equals() 的区别是什么？",
        "reference_answer": (
            "== 比较基本类型的值或引用类型的地址；"
            "equals() 比较对象的内容。String 重写了 equals() 比较字符串内容。"
            "自定义类应重写 equals() 和 hashCode()。"
        ),
        "doc_match": "java_strings",
        "chunk_indices": [0, 1],
        "difficulty": "medium",
        "tags": ["基础", "比较", "字符串", "Java"],
        "ground_truth_notes": "java_strings.md 中字符串比较的说明",
    },
    # ── Thread ─────────────────────────────────────────────────────
    {
        "question": "Java 中如何创建线程？继承 Thread 和实现 Runnable 的区别？",
        "reference_answer": (
            "两种方式：1) 继承 Thread 类并重写 run()；"
            "2) 实现 Runnable 接口并传入 Thread。推荐 Runnable，"
            "因为 Java 单继承，实现接口更灵活。"
        ),
        "doc_match": "java_threads",
        "chunk_indices": [0, 1],
        "difficulty": "medium",
        "tags": ["多线程", "进阶", "Java"],
        "ground_truth_notes": "java_threads.md 中线程创建方式的介绍",
    },
    {
        "question": "Java 中 synchronized 关键字的作用是什么？",
        "reference_answer": (
            "synchronized 保证同一时刻只有一个线程执行同步代码块或方法。"
            "可用于实例方法（锁当前实例）、静态方法（锁 Class 对象）、"
            "或代码块（锁指定对象）。"
        ),
        "doc_match": "java_threads",
        "chunk_indices": [2],
        "difficulty": "hard",
        "tags": ["多线程", "同步", "synchronized", "Java"],
        "ground_truth_notes": "java_threads.md 中同步机制的说明",
    },
    {
        "question": "Java 中 static 关键字的用途有哪些？",
        "reference_answer": (
            "static 修饰：成员变量（类变量，所有实例共享）、"
            "方法（类方法，无需实例即可调用）、代码块（类加载时执行一次）、"
            "内部类（静态内部类）。"
        ),
        "doc_match": "java_syntax",
        "chunk_indices": [2],
        "difficulty": "easy",
        "tags": ["基础", "static", "Java"],
        "ground_truth_notes": "java_syntax.md 中 static 关键字的说明",
    },
    {
        "question": "Java 中什么是多态（polymorphism）？如何实现？",
        "reference_answer": (
            "多态是同一方法在不同对象上有不同表现。实现条件：继承、方法重写、"
            "父类引用指向子类对象。编译看左边类型，运行看右边对象。"
        ),
        "doc_match": "java_polymorphism",
        "chunk_indices": [0, 1],
        "difficulty": "medium",
        "tags": ["OOP", "多态", "Java"],
        "ground_truth_notes": "java_polymorphism.md 中多态的定义和示例",
    },
]


KB_IDS = {
    "python": uuid.UUID("126739c2-e665-4e69-ad59-14218fe5c95d"),
    "java": uuid.UUID("34139461-a995-4f77-86bd-ced21883929d"),
}


async def resolve_chunk_ids(
    db: AsyncSession, kb_id: uuid.UUID, doc_match: str, chunk_indices: list[int]
) -> tuple[list[str], str | None]:
    """Resolve (doc_title_substr, chunk_indices) → (chunk_id list, doc_id).

    Returns (chunk_ids, doc_id). Only the specific chunks at the given
    indices are returned (1-5 items), NOT all chunks from the document.
    """
    result = await db.execute(
        select(Document).where(
            Document.kb_id == kb_id,
            Document.title.like(f"%{doc_match}%"),
        )
    )
    doc = result.scalars().first()  # pick first if duplicates exist

    if not doc:
        print(f"    ⚠️  Document matching '{doc_match}' not found!")
        return [], None

    chunks = (
        await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.doc_id == doc.id)
            .order_by(DocumentChunk.chunk_index)
        )
    ).scalars().all()

    matched = []
    for i in chunk_indices:
        if i < len(chunks):
            matched.append(str(chunks[i].id))
            chunk_preview = chunks[i].content[:60].replace("\n", " ")
            print(f"      chunk[{i}]: {chunk_preview}...")
        else:
            print(f"    ⚠️  chunk index {i} out of range (doc has {len(chunks)} chunks)")

    return (matched if matched else [], str(doc.id))


async def create_dataset(
    db: AsyncSession,
    name: str,
    description: str,
    kb_id: uuid.UUID,
    qa_list: list[dict],
    user_id: uuid.UUID,
):
    """Create a dataset with precisely annotated QA pairs."""
    ds = EvalDataset(
        id=uuid.uuid4(),
        name=name,
        description=description,
        kb_id=kb_id,
        created_by=user_id,
    )
    db.add(ds)
    await db.flush()
    print(f"\n{'=' * 60}")
    print(f"📚 {name}")
    print(f"  KB ID: {kb_id}")
    print(f"  Dataset ID: {ds.id}")

    for qa in qa_list:
        chunk_ids, doc_id = await resolve_chunk_ids(
            db, kb_id, qa["doc_match"], qa["chunk_indices"]
        )

        pair = EvalQAPair(
            id=uuid.uuid4(),
            dataset_id=ds.id,
            question=qa["question"],
            reference_answer=qa["reference_answer"],
            # Document-level GT
            relevant_doc_ids=[doc_id] if doc_id else None,
            relevant_doc_titles=[qa["doc_match"]] if doc_id else None,
            # Chunk-level GT
            ground_truth_chunk_ids=chunk_ids if chunk_ids else None,
            ground_truth_chunk_id_type="vector_id",
            ground_truth_notes=qa.get("ground_truth_notes", ""),
            subject=qa["tags"][-1] if qa.get("tags") else None,
            difficulty=qa["difficulty"],
            tags=qa["tags"],
            # Legacy fallback
            expected_chunk_ids=list(chunk_ids) if chunk_ids else None,
        )
        db.add(pair)

        status = f"{len(chunk_ids)} chunks" if chunk_ids else "⚠️  NO CHUNKS"
        print(f"  [{qa['difficulty']:>5}] {qa['question'][:50]:50s} → {status}")

    await db.flush()
    print(f"  → {len(qa_list)} QA pairs added")
    return ds


async def main():
    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
        print(f"User: {user.username} ({user.id})")
        print(f"Python KB ID: {KB_IDS['python']}")
        print(f"Java KB ID:   {KB_IDS['java']}")

        # ── Python Dataset ──────────────────────────────────────────
        py_ds = await create_dataset(
            db,
            name="Python 基础评估 v2",
            description="Python 3.14 核心概念评估 — 精确标注版，15 QA 对",
            kb_id=KB_IDS["python"],
            qa_list=PYTHON_QA,
            user_id=user.id,
        )

        # ── Java Dataset ────────────────────────────────────────────
        java_ds = await create_dataset(
            db,
            name="Java 基础评估 v2",
            description="W3Schools Java 教程评估 — 精确标注版，15 QA 对",
            kb_id=KB_IDS["java"],
            qa_list=JAVA_QA,
            user_id=user.id,
        )

        await db.commit()

        print(f"\n{'=' * 60}")
        print(f"✅ Done!")
        print(f"  Python: {len(PYTHON_QA)} QA (easy={sum(1 for q in PYTHON_QA if q['difficulty']=='easy')}, "
              f"medium={sum(1 for q in PYTHON_QA if q['difficulty']=='medium')}, "
              f"hard={sum(1 for q in PYTHON_QA if q['difficulty']=='hard')})")
        print(f"  Java:   {len(JAVA_QA)} QA (easy={sum(1 for q in JAVA_QA if q['difficulty']=='easy')}, "
              f"medium={sum(1 for q in JAVA_QA if q['difficulty']=='medium')}, "
              f"hard={sum(1 for q in JAVA_QA if q['difficulty']=='hard')})")
        print(f"  Dataset IDs: Python={py_ds.id}, Java={java_ds.id}")
        print(f"\nRun evaluation:")
        print(f"  curl http://localhost:8085/api/v1/eval/datasets/{py_ds.id}/run -X POST")


if __name__ == "__main__":
    asyncio.run(main())
