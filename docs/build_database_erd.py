from pathlib import Path
import subprocess
from html import escape

ROOT = Path(__file__).parent
tables = {
 'parents': [('id','PK'),('email','UNIQUE'),('password_hash','')],
 'children': [('id','PK'),('display_name',''),('pin_hash','')],
 'devices': [('id','PK'),('display_name',''),('fingerprint',''),('active_child_id','FK, NULL'),('used_seconds',''),('remaining_seconds','')],
 'parent_children': [('parent_id','PK, FK'),('child_id','PK, FK')],
 'child_devices': [('child_id','PK, FK'),('device_id','PK, FK')],
 'parent_sessions': [('token_hash','PK'),('parent_id','FK'),('csrf_token',''),('expires_at','')],
 'policies': [('child_id','PK, FK'),('enabled',''),('weekday_minutes',''),('weekend_minutes',''),('schedule','JSON')],
 'enrollment_codes': [('code_hash','PK'),('child_id','FK'),('expires_at','')],
 'audit': [('id','PK'),('parent_id','FK'),('child_id','FK'),('action',''),('ts','')],
 'device_commands': [('id','PK'),('device_id','FK'),('child_id','FK'),('parent_id','FK'),('command_type',''),('status','')],
 'time_requests': [('id','PK'),('device_id','FK'),('child_id','FK'),('decided_by','FK, NULL'),('minutes',''),('status','')],
}
links = [
 ('parent_children','parent_id','parents'),('parent_children','child_id','children'),
 ('child_devices','child_id','children'),('child_devices','device_id','devices'),
 ('devices','active_child_id','children'),('parent_sessions','parent_id','parents'),
 ('policies','child_id','children'),('enrollment_codes','child_id','children'),
 ('audit','parent_id','parents'),('audit','child_id','children'),
 ('device_commands','device_id','devices'),('device_commands','child_id','children'),('device_commands','parent_id','parents'),
 ('time_requests','device_id','devices'),('time_requests','child_id','children'),('time_requests','decided_by','parents'),
]
colors = {'parents':'#b45309','children':'#087f8c','devices':'#7048b8'}
out = ['digraph ERD {', 'graph [rankdir=LR, bgcolor="white", pad=0.5, nodesep=0.65, ranksep=2.1, splines=polyline, outputorder=edgesfirst, dpi=170, fontname="Arial", fontsize=25, labelloc=t, label="OPENGUARD KIDS — THIẾT KẾ CSDL N–N\\n11 bảng • 16 liên kết FK → PK\\n "];', 'node [shape=plain, fontname="Arial"];', 'edge [arrowsize=0.8, penwidth=1.5];']
for name, fields in tables.items():
    color = colors.get(name, '#23435c')
    rows = [f'<TR><TD COLSPAN="2" BGCOLOR="{color}"><FONT COLOR="white" POINT-SIZE="19"><B>{name}</B></FONT></TD></TR>']
    for field, badge in fields:
        rows.append(f'<TR><TD PORT="{field}" ALIGN="LEFT"><B>{escape(field)}</B></TD><TD ALIGN="LEFT"><FONT COLOR="#536273">{badge or '&#160;'}</FONT></TD></TR>')
    out.append(f'{name} [label=<<TABLE BORDER="1" COLOR="{color}" CELLBORDER="0" CELLSPACING="0" CELLPADDING="10">'+''.join(rows)+'</TABLE>>];')
for source, field, target in links:
    optional = field in ('active_child_id','decided_by')
    # Layout runs from primary entity to dependent, but arrow direction is FK -> PK.
    out.append(f'{target}:id:e -> {source}:{field}:w [dir=back, arrowtail=normal, color="{colors[target]}", style={"dashed" if optional else "solid"}];')
out += ['{rank=same; parents; children;}', '{rank=same; parent_children; devices; parent_sessions; policies; enrollment_codes;}', '{rank=same; child_devices; audit; device_commands; time_requests;}', 'notes [label=<<TABLE BORDER="0" CELLPADDING="8"><TR><TD ALIGN="LEFT"><B>Thiết kế đề xuất — chưa thay đổi mã nguồn</B></TD></TR><TR><TD ALIGN="LEFT">parents N–N children qua parent_children</TD></TR><TR><TD ALIGN="LEFT">children N–N devices qua child_devices</TD></TR><TR><TD ALIGN="LEFT">Hai bảng trung gian dùng khóa chính ghép gồm cả hai FK.</TD></TR><TR><TD ALIGN="LEFT">Mũi tên: FK → PK. Nét đứt: FK cho phép NULL.</TD></TR><TR><TD ALIGN="LEFT">active_child_id chỉ xác định hồ sơ đang sử dụng thiết bị.</TD></TR><TR><TD ALIGN="LEFT">Các trường phụ được rút gọn; giữ đầy đủ các FK của mô hình.</TD></TR></TABLE>>];', '}']
dot = ROOT / 'database-erd-nn.dot'
dot.write_text('\n'.join(out), encoding='utf-8')
assert len(tables) == 11 and len(links) == 16
for kind in ('png','svg'):
    subprocess.run(['dot',f'-T{kind}',str(dot),'-o',str(ROOT / f'database-erd-nn.{kind}')],check=True)
print('Generated 11 tables and 16 FK-to-PK edges.')

