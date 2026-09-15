"""Load only pure native formatter functions by AST, with pinned source hashes.

No analyzer constructor, native model module imports, database, provider clients or
mock replacement for formatting functions. Only config/skill selection are fixed
to the observed legacy-default layout for this formatter-only test.
"""
from __future__ import annotations
import ast, builtins, importlib, pathlib, typing, hashlib, types
SAFE={'re','math','typing','datetime','collections','collections.abc','json','logging','decimal','enum','functools','dataclasses'}

class PureNativeLoader:
    def __init__(self,root):self.root=pathlib.Path(root);self.modules={};self.loaded=set();self.loading=set();self.hashes={}
    def module(self,name):
        if name in self.modules:return self.modules[name]
        p=self.root/(name.replace('.','/')+'.py')
        text=p.read_text();tree=ast.parse(text);bindings={}
        for n in tree.body:
            if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):bindings[n.name]=n
            elif isinstance(n,(ast.Assign,ast.AnnAssign)):
                targets=n.targets if isinstance(n,ast.Assign) else [n.target]
                for t in targets:
                    if isinstance(t,ast.Name):bindings[t.id]=n
            elif isinstance(n,(ast.Import,ast.ImportFrom)):
                for alias in n.names:bindings[alias.asname or alias.name.split('.')[0]]=n
        env={'__builtins__':builtins.__dict__,'__name__':name};env.update(vars(typing))
        self.modules[name]=(p,text,bindings,env);self.hashes[str(p.relative_to(self.root))]=hashlib.sha256(p.read_bytes()).hexdigest()
        return self.modules[name]
    def load(self,module,name):
        if module in SAFE:return getattr(importlib.import_module(module),name)
        p,text,bindings,env=self.module(module);key=(module,name)
        if key in self.loaded or key in self.loading:return env.get(name)
        if name not in bindings:
            if name in env:return env[name]
            raise NameError((module,name))
        n=bindings[name];self.loading.add(key)
        if isinstance(n,ast.ImportFrom):
            if n.level:raise ValueError('Relative import not needed in checked formatter closure')
            a=next(a for a in n.names if (a.asname or a.name)==name)
            env[name]=self.load(n.module,a.name)
        elif isinstance(n,ast.Import):
            a=next(a for a in n.names if (a.asname or a.name.split('.')[0])==name)
            if a.name not in SAFE:raise ValueError('Unsafe module import '+a.name)
            env[name]=importlib.import_module(a.name)
        else:
            self.dependencies(module,n)
            unit=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),n],type_ignores=[])
            ast.fix_missing_locations(unit);exec(compile(unit,str(p),'exec'),env)
        self.loading.remove(key);self.loaded.add(key);return env.get(name)
    def dependencies(self,module,n):
        p,text,bindings,env=self.module(module)
        local={x.id for x in ast.walk(n) if isinstance(x,ast.Name) and isinstance(x.ctx,ast.Store)}
        local.update(x.arg for x in ast.walk(n) if isinstance(x,ast.arg))
        local.update(x.name for x in ast.walk(n) if isinstance(x,(ast.FunctionDef,ast.ClassDef)))
        # Only runtime-loaded bindings, excluding annotation-only Config et al.
        annotations=set()
        for x in ast.walk(n):
            ann=x.annotation if isinstance(x,(ast.arg,ast.AnnAssign)) else x.returns if isinstance(x,ast.FunctionDef) else None
            if ann:annotations.update(id(y) for y in ast.walk(ann))
        names={x.id for x in ast.walk(n) if isinstance(x,ast.Name) and isinstance(x.ctx,ast.Load) and id(x) not in annotations}
        for dep in names-local:
            if dep in bindings:self.load(module,dep)
    def method(self,module,cls,name):
        p,text,bindings,env=self.module(module)
        node=next(n for n in bindings[cls].body if isinstance(n,ast.FunctionDef) and n.name==name)
        self.dependencies(module,node)
        unit=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),node],type_ignores=[])
        ast.fix_missing_locations(unit);exec(compile(unit,str(p),'exec'),env)
        return env[name]
    def formatter(self):
        methods={n:self.method('src.analyzer','GeminiAnalyzer',n) for n in ['_format_prompt','_format_volume','_format_amount']}
        methods['_get_skill_prompt_sections']=lambda self:('','',True)
        methods['_get_runtime_config']=lambda self:types.SimpleNamespace(news_max_age_days=3,news_strategy_profile='short')
        return type('IsolatedFrozenFormatter',(),methods)()
