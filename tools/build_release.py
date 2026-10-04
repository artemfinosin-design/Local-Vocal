"""Build the launcher and integrity manifest without any user data."""
from pathlib import Path
import hashlib,json,os,re,subprocess,sys
from zipfile import ZipFile,ZIP_DEFLATED

root=Path(__file__).resolve().parents[1];studio=root/'karaoke-studio';dist=root/'dist';dist.mkdir(exist_ok=True)
version=int(re.search(r'^BACKEND_VERSION\s*=\s*(\d+)',(studio/'runtime.py').read_text(encoding='utf-8'),re.M)[1])
if os.environ.get('GITHUB_REF_TYPE')=='tag':assert os.environ['GITHUB_REF_NAME']==f'v0.{version}.0','Tag must match BACKEND_VERSION'
command=[sys.executable,'-m','PyInstaller','--noconfirm','--onefile','--windowed','--name','SvoyaVersiya',
         '--icon',str(studio/'app.ico'),'--distpath',str(dist),'--workpath',str(root/'build'),'--specpath',str(root/'build')]
for module in ('torch','scipy','numpy','matplotlib','IPython','imageio_ffmpeg'):command+=['--exclude-module',module]
subprocess.run(command+[str(studio/'desktop.py')],check=True)
files=json.loads((root/'release-files.json').read_text(encoding='utf-8'))
archive=dist/f'karaoke-studio-beta{version}.zip';records={}
with ZipFile(archive,'w',ZIP_DEFLATED) as z:
    for name in files:
        source=dist/name if name=='SvoyaVersiya.exe' else studio/name
        data=source.read_bytes();records[name]=dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
        z.writestr('karaoke-studio/'+name,data)
with ZipFile(archive) as z:assert z.testzip() is None
manifest=dict(schema=1,version=version,asset=archive.name,bytes=archive.stat().st_size,
              sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),files=records)
(dist/'update-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print('Release ready:',archive.name)
