# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Isolated real browser: open a SUM group, edit state, save, and inspect the queue."""
import json
from pathlib import Path
import tempfile
from uuid import uuid4
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineUrlRequestInterceptor
from spikes.artifacts import Artifacts, main_todo_id
from spikes.chat_service import ChatService
from spikes.desktop import request_policy
from spikes.desktop_ui import DesktopHandler
from spikes.local_api import running_api
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects

BODY = '''<!-- fpw-plan-profile: software-development/v1 -->
- [ ] [MILESTONE-01] Milník
  - type: milestone
  - status: sum
  - [ ] [BATCH-01] Stavová dávka
    - type: batch
    - status: sum
    - [ ] [TASK-01] První úkol
      - type: task
'''


def main():
    app = QApplication([])
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); node = root/'node.json'
        pid = ProjectCreation(node).create('Status smoke', str(root/'project'), str(uuid4()))['id']
        projects = Projects(node); head = projects.open(pid)['commit_id']
        Artifacts(node).save(dict(project_id=pid, artifact_id=main_todo_id(pid), base_head=head,
            title='Roadmapa', body=BODY, new=True), str(uuid4()))
        with running_api('http', handler=DesktopHandler, projects=projects) as server:
            server.chat_service = ChatService(node, projects)
            class Interceptor(QWebEngineUrlRequestInterceptor):
                def interceptRequest(self, info):
                    policy = request_policy(info.requestUrl().toString(), info.initiator().toString(),
                                            bytes(info.requestMethod()).decode(), server.origin)
                    if policy == 'block': info.block(True)
                    elif policy == 'authenticate':
                        info.setHttpHeader(b'Authorization', ('Bearer '+server.token).encode())
            profile = QWebEngineProfile(app); interceptor = Interceptor(profile)
            profile.setUrlRequestInterceptor(interceptor)
            view = QWebEngineView(); page = QWebEnginePage(profile, view); view.setPage(page)
            view.resize(1280, 900); view.show()
            phase = 0
            checks = [
                "typeof openRegisteredProject==='function'",
                "activeProject&&taskPlanProjection?.status==='ready'&&queueIsCurrent()",
                "!document.querySelector('#plan-panel').hidden&&document.querySelector('#plan-graph').getBoundingClientRect().top<350&&document.querySelector('.plan-batch-card .plan-status-badge')?.textContent==='SUM · Plánováno'",
                "document.querySelector('#plan-item-status-control select')?.value==='sum'&&!artifactEditorView.hidden",
                "artifactEditorDirty&&artifactEditorForm.elements.body.value.includes('status: in progress')",
                "taskPlanProjection?.nodes.find(n=>n.id==='BATCH-01')?.status==='in progress'&&artifactEditorView.hidden&&queueIsCurrent()",
                "taskQueueView?.items.some(i=>i.id==='BATCH-01'&&i.status==='in progress')&&document.querySelector('#task-queue-list .plan-status-badge')?.textContent==='Probíhá'",
            ]
            commands = [
                'openRegisteredProject('+json.dumps(pid)+')',
                'openTaskPlan()',
                "openPlanItemEditor(taskPlanProjection.nodes.find(n=>n.id==='BATCH-01'))",
                "(()=>{const s=document.querySelector('#plan-item-status-control select');s.value='in progress';s.dispatchEvent(new Event('change'));})()",
                'savePlanItemEditor()',
                "changeTaskQueue('add','BATCH-01')",
            ]
            def received(value):
                nonlocal phase
                if value != 'ready': return
                if phase == len(commands):
                    view.grab().save('/tmp/fpw-plan-status-smoke.png')
                    print('plan status browser OK', flush=True); app.exit(0); return
                command = commands[phase]; phase += 1; page.runJavaScript(command)
            def poll():
                page.runJavaScript('('+checks[phase]+')?"ready":"waiting"', received)
            timer = QTimer(); timer.timeout.connect(poll); timer.start(180)
            QTimer.singleShot(25000, lambda: page.runJavaScript(
                "JSON.stringify({top:document.querySelector('#plan-graph').getBoundingClientRect().top,badge:document.querySelector('.plan-batch-card .plan-status-badge')?.textContent,panel:document.querySelector('#plan-panel').hidden,status:document.querySelector('#plan-status').textContent,editor:artifactEditorStatus.textContent,queue:document.querySelector('#task-queue-status').textContent})",
                lambda value: (view.grab().save('/tmp/fpw-plan-status-timeout.png'),print('timeout', phase, value, flush=True), app.exit(2))))
            page.setUrl(QUrl(server.origin+'/'))
            return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
