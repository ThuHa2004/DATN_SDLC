"""Opt-in real Docker checks: PYTHONPATH=backend python backend/tests/verify_docker_runtimes.py."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.agents.module_runner import build_test_plans, run_test_plan
from app.agents.pipeline_runner import PipelineRunner


class DockerRuntimeChecks(unittest.IsolatedAsyncioTestCase):
    async def test_python_node_and_static_with_system_and_regression(self):
        with tempfile.TemporaryDirectory(prefix="sdlc-runtime-check-") as directory:
            root=Path(directory)
            fixtures={
                "python": {
                    "requirements.txt":"fastapi\nsqlalchemy\nhttpx\n",
                    "app.py": """from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, Session
from sqlalchemy.pool import StaticPool
engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
Base=declarative_base()
class Item(Base):
    __tablename__='items'
    id=Column(Integer,primary_key=True)
    name=Column(String,nullable=False)
class CreateItem(BaseModel):
    name:str=Field(min_length=1)
Base.metadata.create_all(engine)
app=FastAPI()
@app.post('/items',status_code=201)
def create_item(payload:CreateItem):
    with Session(engine) as db:
        item=Item(name=payload.name); db.add(item); db.commit(); db.refresh(item)
        return {'id':item.id,'name':item.name}
@app.get('/items/{item_id}')
def get_item(item_id:int):
    with Session(engine) as db:
        item=db.get(Item,item_id)
        if item is None: raise HTTPException(404,'Not found')
        return {'id':item.id,'name':item.name}
""",
                    "tests/test_system.py": """from fastapi.testclient import TestClient
from app import app
def test_actual_api_database_flow():
    with TestClient(app) as client:
        created=client.post('/items',json={'name':'demo'})
        assert created.status_code==201
        item=created.json()
        assert client.get('/items/'+str(item['id'])).json()==item
        assert client.post('/items',json={'name':''}).status_code==422
        assert client.get('/items/99999').status_code==404
"""},
                "node": {
                    "package.json":json.dumps({"type":"module","dependencies":{"express":"^4.21.0"},"devDependencies":{"vitest":"^3.2.0","supertest":"^7.0.0"},"scripts":{"build":"node --check app.js"}}),
                    "vitest.config.js":"export default {test:{include:['src/**/*.test.js']}};",
                    "app.js":"""import express from 'express';
export const app=express(); app.use(express.json()); const items=[];
app.post('/items',(req,res)=>{if(typeof req.body.name!=='string'||!req.body.name.trim())return res.status(400).json({error:'name required'});const item={id:items.length+1,name:req.body.name};items.push(item);res.status(201).json(item)});
app.get('/items/:id',(req,res)=>{const item=items.find(x=>x.id===Number(req.params.id));if(!item)return res.status(404).json({error:'not found'});res.json(item)});
""",
                    "tests/system.test.js":"""import {test,expect} from 'vitest'; import request from 'supertest'; import {app} from '../app.js';
test('actual API flow',async()=>{const created=await request(app).post('/items').send({name:'demo'}).expect(201);const got=await request(app).get('/items/'+created.body.id).expect(200);expect(got.body).toEqual(created.body);await request(app).post('/items').send({name:''}).expect(400);await request(app).get('/items/99999').expect(404)});
"""},
                "static": {"index.html":"<!doctype html><html><body><h1>Working website</h1></body></html>",
                           "tests/system.test.js":"import {test,expect} from 'vitest'; import fs from 'node:fs'; test('HTML',()=>{document.documentElement.innerHTML=fs.readFileSync('index.html','utf8');expect(document.querySelector('h1').textContent).toBe('Working website')});"},
            }
            for name,files in fixtures.items():
                for filename,code in files.items():
                    path=root/name/filename; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(code,encoding="utf-8")
            async def verify(name):
                folder=root/name
                result=await run_test_plan(folder,build_test_plans(folder)[0],strict=True,regression=True)
                self.assertEqual(result["status"],"passed",result["log"][-8000:])
            await asyncio.gather(*(verify(name) for name in fixtures))

    async def test_real_compose_preview_and_assets(self):
        with tempfile.TemporaryDirectory(prefix="sdlc-preview-check-") as directory:
            sandbox=Path(directory); root=sandbox/"verification"; root.mkdir()
            (root/"index.html").write_text('<!doctype html><html><head><link rel="stylesheet" href="/style.css"></head><body><h1>Preview</h1></body></html>')
            (root/"style.css").write_text('body {color:#123456}')
            (root/"docker-compose.yml").write_text(json.dumps({"services":{"frontend":{"image":"nginx:alpine","container_name":"must-not-be-used","ports":["127.0.0.1:9999:80"],"volumes":[{"type":"bind","source":str(root.resolve()),"target":"/usr/share/nginx/html","read_only":True}]}}}))
            runner=PipelineRunner.__new__(PipelineRunner)
            with patch("app.services.file_service.SANDBOX_DIR",sandbox):
                try:
                    result=await runner._start_docker("verification",runner._available_port())
                    self.assertEqual(result["status"],"passed",result["log"])
                    self.assertTrue(result["preview_url"].startswith("http://localhost:"))
                    config=json.loads((root/".sdlc/compose.preview.json").read_text())
                    self.assertNotIn("container_name",config["services"]["frontend"])
                finally:
                    config=root/".sdlc/compose.preview.json"
                    if config.exists():
                        await runner._command(["docker","compose","--project-directory",str(root),"-p","sdlc-verification","-f",str(config),"down","--remove-orphans"],root,timeout=60)


if __name__ == "__main__":
    unittest.main(verbosity=2)
