"""A deterministic mock research narrative, separate from measured studies."""
from pathlib import Path
from datetime import datetime, timedelta
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]


def make_demo():
    stamp = '2026-10-20T09:00:00+08:00'
    def node(id, title, kind, status, x, y, summary='', parent=None, **extra):
        return dict(id=id, title=title, kind=kind, status=status, parentId=parent,
                    summary=summary, notes='', nextAction='', tags=[], position=dict(x=x, y=y),
                    collapsed=False, createdAt=stamp, updatedAt=stamp, **extra)
    nodes = [
        node('goal', '让检索更快，也更准确', 'goal', 'active', 380, 30,
             '比较关键词、向量与混合检索；在质量约束下寻找更低的查询延迟。',
             ),
        node('baseline', '建立可复核的基线', 'experiment', 'completed', 100, 290,
             '固定语料与查询集合，记录线性扫描的结果和耗时。'),
        node('candidates', '三种算法，一起探索', 'group', 'active', 500, 290,
             '关键词、向量与混合检索，从不同角度验证同一个问题。'),
        node('bm25', '关键词：BM25', 'algorithm', 'completed', 535, 380,
             '精确关键词表现稳定，检查同义表达时的召回。', 'candidates'),
        node('dense', '向量：语义相似度', 'algorithm', 'rejected', 845, 380,
             '语义召回改善，但本地资源消耗超出本轮预算。', 'candidates'),
        node('hybrid', '融合策略', 'group', 'active', 690, 620,
             '融合关键词与语义结果，继续检验收益是否稳定。', 'candidates'),
        node('rrf', 'RRF 排名融合', 'algorithm', 'completed', 725, 710,
             '用排序融合避免不同检索分数的量纲冲突。', 'hybrid'),
        node('weighted', '加权分数融合', 'algorithm', 'paused', 1035, 710,
             '权重敏感，保留这条分支，等待更多查询样本。', 'hybrid'),
        node('failure', '分数尺度不一致', 'finding', 'completed', 100, 790,
             '直接相加导致排名偏置；保留失败结果，修订融合方法。'),
        node('quality', '先确认质量，再看速度', 'experiment', 'completed', 100, 545,
             '固定输入上检查 Recall@5，并补计索引准备成本。'),
        node('decision', '保留融合，继续验证', 'decision', 'active', 500, 925,
             '当前样本支持保留候选，下一轮验证语料更新和长尾查询。'),
        node('updates', '动态语料与更新成本', 'plan', 'proposed', 500, 1160,
             '改变语料后重建索引，评估更新成本与结果一致性。'),
    ]
    nodes[0]['nextAction'] = '继续验证融合方案在动态语料上的表现'
    nodes[0]['tags'] = ['检索研究', '质量与成本']
    nodes[2]['collapsed'] = True
    nodes[5]['collapsed'] = True
    nodes[5]['nextAction'] = '扩大查询集，检查 RRF 排名稳定性'
    nodes[10]['nextAction'] = '加入语料更新和长尾查询'
    nodes[8]['notes'] = '模拟研究记录：BM25 与向量相似度分数不在同一尺度。直接相加让高分支配排名。保留原始排名，转向无需分数标定的 RRF。'
    nodes[9]['notes'] = '初次评估遗漏了索引准备成本。复用原始运行产物修订评价，不新增一次运行。'
    nodes[7]['pauseReason'] = '本轮优先验证 RRF；加权方案尚未完成分数归一化修订。'
    nodes[7]['resumeWhen'] = '明确归一化口径并补齐长尾查询样本后。'
    nodes[7]['nextAction'] = '验证归一化后的权重稳定性。'
    for index, reason in [(8, '反例推翻了直接相加分数的比较依据，触发融合路线转向。'),
                          (9, '补计准备成本改变了收益口径，需修订原评价。'),
                          (10, '决定当前保留路线及下一轮验证范围。')]:
        nodes[index]['importance'] = 'critical'
        nodes[index]['importanceReason'] = reason
    links = [
        ('goal', 'baseline', 'branches', '固定输入'), ('goal', 'candidates', 'branches', '并行探索'),
        ('baseline', 'quality', 'tests', '质量基线'), ('candidates', 'failure', 'leads_to', '发现偏置'),
        ('bm25', 'rrf', 'uses', '关键词排序'), ('dense', 'rrf', 'uses', '语义排序'),
        ('failure', 'hybrid', 'revises', '修订策略'), ('quality', 'decision', 'supports', '质量约束'),
        ('failure', 'decision', 'motivates', '保留失败依据'), ('rrf', 'decision', 'supports', '融合结果'),
        ('decision', 'updates', 'leads_to', '下一轮验证'), ('updates', 'candidates', 'revisits', '回访候选'),
    ]
    edges = [dict(id=f'e-{i}', source=s, target=t, relation=r, label=l,
                  basis='hypothesis' if r in ('branches', 'revisits') else 'observed') for i, (s,t,r,l) in enumerate(links)]
    def run(id, node_id, title, status, method, metrics, events):
        return dict(id=id, nodeId=node_id, title=title, status=status, origin='mock',
                    configuration=dict(method=method, corpus='demo-corpus-v1', queries='demo-query-set-v1',
                                       cases=40, hardware='demo-local', inputSignature='mock-fixture-v1'),
                    metrics=metrics, startedAt=stamp, finishedAt=stamp, artifactIds=[],
                    events=[dict(id=f'{id}-event-{i}', type=kind, message=message, at=stamp)
                            for i,(kind,message) in enumerate(events)])
    runs = [
        run('run-baseline','baseline','线性扫描 · 基线','completed','linear',{'latency_ms':42.8,'recall_at_5':.78}, [('start','固定语料和查询集'),('delivery','保存排名与查询耗时')]),
        run('run-bm25','bm25','BM25 · 关键词','completed','bm25',{'latency_ms':8.6,'recall_at_5':.81}, [('start','建立关键词索引'),('delivery','输出排名，保留未命中案例')]),
        run('run-dense','dense','向量 · 语义','completed','dense',{'latency_ms':38.2,'recall_at_5':.86}, [('start','建立语义索引'),('delivery','结果已保存；资源成本偏高')]),
        run('run-weighted','failure','直接分数融合 · 失败','invalid','weighted',{'recall_at_5':.69}, [('start','尝试直接相加'),('error','分数尺度不一致，排名偏置；不进入正式收益比较')]),
        run('run-rrf','rrf','RRF · 排名融合','completed','rrf',{'latency_ms':14.2,'recall_at_5':.89}, [('start','复用两路检索排名'),('delivery','输出融合排名及原始计时')]),
    ]
    folder = ROOT / 'examples' / 'demo' / 'evidence'
    folder.mkdir(parents=True, exist_ok=True)
    fixtures = [
        ('ranking-csv','模拟排名与指标','metrics.csv','method,latency_ms,recall_at_5\nlinear,42.8,0.78\nbm25,8.6,0.81\ndense,38.2,0.86\nrrf,14.2,0.89\n','text/csv','run-rrf','rrf'),
        ('failure-log','分数融合失败记录','weighted-failure.txt','MOCK RESEARCH FIXTURE\nBM25 score range: 0..22\nDense similarity range: 0..1\nDirect score sum overweights BM25.\nConclusion: evaluate ranking fusion rather than adding raw scores.\n','text/plain','run-weighted','failure'),
        ('eval-json','评价口径与修订','assessment.json',json.dumps({'origin':'mock','rubric':'retrieval-v1','qualityGate':{'metric':'recall_at_5','minimum':.8},'revision':'Preparation cost added; original run reused.'},ensure_ascii=False,indent=2),'application/json','run-rrf','quality'),
        ('notes-md','研究决策记录','decision.md','# 模拟研究决策\n\n保留 RRF 候选，继续验证动态语料。\n\n当前结果仅用于演示记录、修订与证据关联。\n\n下一步：增加长尾查询，并计入索引更新成本。\n','text/markdown',None,'decision'),
    ]
    artifacts=[]
    for id,title,name,content,mime,run_id,node_id in fixtures:
        path=folder/name
        path.write_text(content,encoding='utf-8')
        raw=path.read_bytes()
        artifacts.append(dict(id=id,title=title,path=str(path),sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),mime=mime,runId=run_id,nodeId=node_id,origin='mock',createdAt=stamp))
        for r in runs:
            if r['id']==run_id:r['artifactIds'].append(id)
    assessments=[dict(id=f'assess-{r["id"]}',runId=r['id'],rubric='retrieval-v1',metrics=r['metrics'],conclusion={'linear':'基线质量低于本轮目标。','bm25':'关键词质量达标；继续检查同义表达。','dense':'质量改善，查询成本偏高。','weighted':'运行无效，不纳入收益判断。','rrf':'模拟样本中质量与延迟达到候选要求。'}[r['configuration']['method']],limitations='模拟数据，用于演示研究记录；不代表性能实测。',supersedes=None,artifactIds=r['artifactIds'],createdAt=stamp) for r in runs]
    assessments[-1]['metrics']={'latency_ms':12.1,'recall_at_5':.89}
    assessments.append(dict(id='assess-rrf-revised',runId='run-rrf',rubric='retrieval-v1',metrics={'latency_ms':14.2,'recall_at_5':.89},conclusion='补计准备成本后仍保留 RRF 候选。',limitations='固定模拟输入，尚未验证语料更新成本。',supersedes='assess-run-rrf',artifactIds=['ranking-csv','eval-json'],createdAt=stamp))
    observations = []
    for index, (node_id, seconds, input_tokens, output_tokens) in enumerate([
        ('goal', 45, 1200, 250), ('baseline', 60, 1800, 420),
        ('candidates', 20, 650, 180), ('bm25', 90, 2200, 540), ('dense', 120, 2800, 620),
        ('hybrid', 15, 700, 160), ('rrf', 75, 2300, 490), ('weighted', 40, 1500, 350),
        ('failure', 30, 1300, 380), ('quality', 45, 1700, 420), ('decision', 20, 900, 240),
    ]):
        start = datetime.fromisoformat(stamp) + timedelta(minutes=index * 3)
        end = start + timedelta(seconds=seconds)
        observations.append(dict(id=f'mock-step-{node_id}',nodeId=node_id,title=f'模拟步骤 · {next(n["title"] for n in nodes if n["id"] == node_id)}',
                                 status='finished',startedAt=start.isoformat(),finishedAt=end.isoformat(),durationMs=seconds*1000,
                                 inputTokens=input_tokens,outputTokens=output_tokens,usageSource='mock-runtime-counter',usageRef=f'mock-{node_id}',origin='mock'))
    return dict(id='retrieval-demo',name='检索策略 · 研究演示',description='在质量约束下探索更快的检索：从基线、算法分支，到失败修订与下一轮研究。',revision=1,createdAt=stamp,updatedAt=stamp,sourceRoots=[str(folder.parent)],observations=observations,nodes=nodes,edges=edges,runs=runs,artifacts=artifacts,assessments=assessments,decisions=[dict(id='decision-keep',nodeId='decision',title='保留 RRF 候选',conclusion='融合排名在当前模拟样本中取得更好的质量与查询成本平衡。',scope='固定模拟语料和查询，尚未验证动态更新。',nextAction='测试语料更新与长尾查询',runIds=['run-baseline','run-rrf'],artifactIds=['ranking-csv','notes-md'],createdAt=stamp)],activity=[dict(id='demo-event-1',at=stamp,message='建立基线与固定查询集'),dict(id='demo-event-2',at=stamp,message='并行探索三种检索算法'),dict(id='demo-event-3',at=stamp,message='发现分数融合偏置，修订方法'),dict(id='demo-event-4',at=stamp,message='补计准备成本，保留旧评估'),dict(id='demo-event-5',at=stamp,message='保留 RRF 候选，开启动态语料研究')])
