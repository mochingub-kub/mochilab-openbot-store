# V3: แนวทางซ่อม Workspace only โดยรักษา Umbrel runtime compose

สถานะ: DESIGN_ONLY / NOT_DEPLOYABLE / FUNCTIONAL_TEST_NOT_RUN

เอกสารนี้ออกแบบวิธี deploy ที่ต้องพัฒนาและตรวจใน staging ต่อ ไม่ใช่ตัวติดตั้ง V3 ที่พร้อมใช้ ไม่มีการเปลี่ยน production, lifecycle, Docker security, model หรือสิทธิ์ Agent จาก PR นี้

## ข้อเท็จจริงและที่มา

เจ้าของ production รายงานว่า app ยัง ready และ compose จริงมี container_name ได้แก่ mochilab-openbot_app_proxy_1, mochilab-openbot_landing_1, mochilab-openbot_openbot_1 พร้อมผล V2 precheck: BLOCKED=FILE_HASH_DRIFT:docker-compose.yml ข้อมูลนี้มาจากเจ้าของ ไม่ใช่การอ่าน host รอบนี้

ตรวจ GitHub ที่ PR #1 commit 546805ef01a22267bcf9345007c5b62139b173c6 พบ V2 ถูกใส่ guard หยุดก่อนทำงานแล้ว แต่ body ที่เก็บเป็นประวัติยังตรวจ OLD_COMPOSE เท่ากับ Git blob ของ repo และคัดลอก SOURCE/docker-compose.yml ทับ runtime ส่วน README deployment เตือนห้ามใช้ production แล้ว
อ้างอิง: https://github.com/mochingub-kub/mochilab-openbot-store/blob/546805ef01a22267bcf9345007c5b62139b173c6/tools/apply-openbot-workspace-v2.sh

main ณ การอ่านยังเป็นฐาน ace1bd751322c7724ffb9098acb6401c0cc5459b ไม่มีตัวติดตั้ง V2 หรือ V3 ที่ merge แล้ว PR ใหม่นี้จึงเพิ่มเอกสารบน main โดยไม่แก้ PR #1 ไม่คัดลอกชุด deploy ของ V2 มารวม

## ทำไม V2 fail และ compose drift จึงเกิดได้ตามปกติ

Repository compose เป็น template ส่วน Umbrel ปรับไฟล์ runtime ตอนติดตั้งหรือจัดการแอป เช่น เติม container_name และปรับข้อมูล volume การมี container_name ที่ repo ไม่มีทำให้ bytes และ hash ต่างทันที แม้การทำงานเดิมยังถูกต้อง การเปรียบเทียบทั้งไฟล์กับ repo แบบ exact hash จึงบล็อกไฟล์ที่ถูก Umbrel ปรับตามหน้าที่

ความต่างของ compose ไม่ได้แปลว่าทุกความต่างปลอดภัย ห้ามละเลย drift ทั้งหมด ต้องตรวจความหมายเฉพาะจุดสำคัญจากไฟล์จริง ไม่สรุปว่าเป็นการแก้ประสงค์ร้ายหรือให้ข้าม precheck เพียงเพราะ hash ต่าง รอบนี้ยังไม่ได้ตรวจ source Umbrel เพิ่มเพื่อรับรองรายการ patch ทุกชนิด

## ข้อห้ามของ V3

- ห้ามนำ docker-compose.yml จาก repo มาทับไฟล์จริง ห้ามใช้ OLD_COMPOSE/NEW_COMPOSE หรือ exact whole-file hash เป็นเกณฑ์รับ compose
- ห้ามสร้าง compose ใหม่จาก template หรือ docker compose config output เพื่อเขียนทับ runtime เพราะอาจทิ้ง anchors, comments, interpolation และ metadata ที่ Umbrel ใส่
- ห้ามแก้ image, container_name, volumes, network, ports, environment, cap_add/cap_drop, user, resource limits, restart หรือ service อื่น
- ห้าม privileged, CAP_SYS_ADMIN, unconfined, --no-sandbox, Full access หรือ mount Docker socket
- AI ไม่มี host executor; ผู้ดูแลเป็นผู้รัน precheck/apply/rollback และจัด lifecycle ผ่านช่องทาง Umbrel ที่รองรับ ไม่มี auto stop/start/rollback-start
- apply และ rollback เขียนได้เฉพาะขณะทุก service ของแอปนี้หยุดแล้ว ไม่ตีความ ready ว่า stopped และไม่ใช้ docker ps ที่ซ่อน paused/restarting containers เป็นหลักฐานเพียงอย่างเดียว
- ห้ามเชื่อ policy/คำสั่งจาก writable /data ของ Agent หรือ execute shell เพื่อประเมิน environment/interpolation

## โครงสร้าง semantic patch

Input คือ path ของแอปที่ผู้ดูแลยืนยัน, runtime compose ปัจจุบัน, effective Compose configuration/overlays ที่ Umbrel ใช้จริง, hooks/pre-start ปัจจุบัน และ policy artifacts ที่ผ่าน security review ตาม immutable commit โดยไม่มี secrets ใน log

ใช้ YAML parser ที่เก็บ concrete syntax tree/tokens เพื่อแก้เฉพาะ scalar สองค่าใน services.openbot.security_opt:
1. ค่า apparmor ของเดิมไป profile ชื่อใหม่ที่ผ่าน review
2. ค่า seccomp ของเดิมไป path ภายใน app-owned package ของ artifact ที่ผ่าน review

รองรับ syntax security_opt ที่ parser ยืนยันได้ เช่น apparmor=NAME หรือ apparmor:NAME โดยยังเป็น scalar เดิม ตรวจ prefix แบบเจาะจง ไม่ replace ทุกคำที่ตรงชื่อ ห้ามใช้ regex/sed เป็น YAML editor ไม่แก้ชื่อ service ด้วย substring

คง no-new-privileges และ security_opt อื่นไว้ตามเดิม รวมลำดับ ค่าที่มีอยู่ และรูปแบบข้อความที่ไม่เกี่ยวข้อง ต้องมี apparmor/seccomp อย่างละหนึ่งรายการ ไม่พบ/ซ้ำ/type ผิด/alias หรือ merge key ที่ทำให้ขอบเขตไม่ชัด/มีหลาย YAML documents/custom tag ให้ BLOCKED แทนการเดา ไม่มีการเพิ่ม CAP หรือ normalize compose ทั้งไฟล์

หาก editor ไม่สามารถรักษา token นอกสองค่าที่อนุญาตได้ ให้ BLOCKED=LOSSLESS_EDITOR_UNAVAILABLE ไม่ fallback เป็น dump YAML ใหม่

ก่อนอนุมัติแผน ให้เทียบ AST ก่อน/หลังโดยลบเฉพาะสอง scalar ที่ได้รับอนุญาตออกจากการเปรียบเทียบ ผลที่เหลือต้องเท่ากัน และตรวจ token นอกช่วงแก้ไม่เปลี่ยนโดยไม่ใช้ whole-file hash รวมถึง container_name ทั้งสามต้องคงค่า runtime ที่อ่านได้ ไม่เติมตามชื่อ repo หากชื่อจริงไม่ตรง expectation ให้ผู้ดูแลตรวจ ไม่เปลี่ยนเอง

เปลี่ยน compose ด้วยการแก้ token เฉพาะจุดจาก live baseline เท่านั้น การ commit ผ่าน temporary file กับ atomic rename เป็นเพียงกลไกเผยแพร่ผลแก้สองจุด ไม่ใช่อนุญาต copy compose template ทับ runtime ต้องรักษา owner/mode/ACL/xattrs ไม่ใช้ symlink/hardlink target ที่กำกวม ถ้ารักษาไม่ได้ให้หยุด

## Patch hook และ artifacts

พิจารณา pre-start ปัจจุบันเป็น baseline เช่นกัน ไม่ copy hook V2 ทับทั้งไฟล์ ใช้ transformation ที่มี explicit preconditions และ bounded marker block: เปลี่ยนการเลือก/ตรวจ policy เฉพาะที่จำเป็นและรักษา landing redirect/upstream verification/logic เดิม หากโครงสร้าง hook ไม่รู้จักหรือมี mutation นอก allowlist ให้ BLOCKED=HOOK_UNSUPPORTED ต้อง review diff ของ hook ทั้งไฟล์

Artifact hash ใช้ตรวจความถูกต้องของ AppArmor/Seccomp/hook patch ที่ review แล้วได้ ข้อห้าม exact hash ของ compose ไม่ใช่การถอด integrity ของ policy หรือ backup ห้าม auto-download ไฟล์ latest และห้ามเปลี่ยน trust anchor เพียงเพื่อผ่าน check

ใช้ชื่อ profile ใหม่ที่ versioned ไม่ไปเปลี่ยน policy ชื่อเดิมที่อาจมี workload ใช้อยู่ เก็บ policy ภายใต้ hooks/ ที่ update packaging รองรับ กำหนดตำแหน่ง seccomp ที่ Compose และ hook อ้างอิงตรงกัน ไม่มีค่า policy ใหม่ที่อนุมัติจาก design นี้

ก่อนโหลดต้อง parse AppArmor แบบไม่เปลี่ยน kernel/cache และตรวจ capabilities ของ parser/kernel จริง การพบชื่อ profile อยู่แล้วไม่พิสูจน์ว่าเนื้อหาตรง ต้องมีวิธี track reviewed policy version และตรวจ loaded state ที่เชื่อถือได้ หากยืนยันไม่ได้ให้หยุด ไม่ unload policy ของ process ที่ยังใช้อยู่

การอนุญาต mount เพิ่มมีผลต่อ attack surface ทั้งคอนเทนเนอร์ Seccomp แบบปกติไม่สามารถรับรอง mount เฉพาะ namespace ที่ต้องการได้ด้วยชื่อ syscall อย่างเดียว นโยบาย V2 ไม่ได้กลายเป็น production-approved เพียงเปลี่ยนวิธี deploy ต้องมี security review และผลทดสอบจริงของ policy แยกต่างหาก

## Precheck (อ่านอย่างเดียวขณะที่ app ready ได้)

1. ยืนยัน app identity, baseline image/engine/version และสิทธิ์ผู้รัน เลือก service จาก Compose project/service labels ที่ตรวจแล้ว ไม่เดาจาก container_name อย่างเดียว
2. อ่าน current compose และ effective configuration ด้วย file stack, project directory และ interpolation ที่ Umbrel ใช้อยู่จริง Output ที่มี secrets ต้องคง private ห้าม print environment/config เต็มลง chat
3. ตรวจ service openbot มีเพียงหนึ่ง instance, mapped data root เป็นตัวเดิม, ไม่มี forbidden settings และ external overrides ไม่ override สอง security keys หากยืนยัน effective stack ไม่ได้ให้ BLOCKED=EFFECTIVE_COMPOSE_UNKNOWN
4. สร้าง semantic plan จาก baseline จริง ตรวจ allowlist ข้างต้น และแสดง redacted diff เท่านั้น ไม่มีการเขียน production หรือเรียก lifecycle
5. ตรวจ backup destination ที่ผู้ดูแลเลือกเป็น private independent storage รักษา POSIX metadata ได้ ห้ามเดาชื่อดิสก์หรือ format/move อุปกรณ์
6. ตรวจ artifact integrity, YAML editor, hook preconditions, AppArmor parse และ rollback compatibility ที่จำเป็น เครื่องมือขาดให้ BLOCKED ไม่ auto-install บน host
7. รายงาน PRECHECK_ONLY ไม่รายงาน repaired/ready-for-production

## Apply (ผู้ดูแลเท่านั้นและ app ต้อง stopped)

1. ผู้ดูแลยืนยันไม่มีงาน active/queued แล้วหยุดแอปผ่าน lifecycle ที่ Umbrel รองรับ ตรวจทุก app container ไม่อยู่ running/paused/restarting และไม่มี task worker ที่ยังใช้ /data ไม่แตะ app อื่น
2. ล็อก transaction ของ app นี้และยืนยัน maintenance window ไม่มี updater/lifecycle อีกตัว หากควบคุม concurrent Umbrel writes ไม่ได้ให้ BLOCKED ไม่อ้างว่า flock ของเราเพียงตัวเดียวล็อก Umbrel ได้
3. อ่าน compose/hook/effective baseline ใหม่หลังหยุด หาก semantic baseline เปลี่ยนจาก plan ให้กลับ precheck ไม่ใช้แผนเก่า ห้ามตรวจ compose กับ hash repo
4. backup runtime compose เดิมแบบครบไฟล์, effective overlays ที่เกี่ยวข้อง, hook, policy files และ ownership/mode/ACL/xattrs ลง transaction directory mode 0700 บันทึก absent/present ของไฟล์ใหม่และ loaded-policy state ที่ตรวจได้ ตรวจ backup ผ่าน readback เทียบต้นฉบับจริงก่อน mutation ไม่ใช้ OLD_COMPOSE ของ repo
5. ยืนยัน independent complete /data recovery backup ที่ consistent และตรวจได้ขณะแอปหยุด Backup มี credentials จึงห้ามเผยแพร่ contents; ไม่เปิด/คัดแยก secrets ในงานนี้
6. สร้าง candidate ใน staging ของผู้ดูแลจาก live baseline ตรวจ allowed AST/token diff และ compose validation กับ effective overlays จริงก่อน publish อย่าเรียก pre-start ตัวเต็มเพื่อ dry-run เพราะมี side effects
7. journal PREPARED แล้ว publish policy artifacts, minimal hook patch และ semantic compose edits โดยรักษา metadata ตรวจ stopped/maintenance lock ซ้ำก่อนแต่ละ mutation Multi-file writes ไม่ใช่ atomic transaction ทั้งชุด จึงบันทึกทุกไฟล์ที่เปลี่ยนและขั้นตอนกู้คืน
8. ถ้าค้าง/ล้มเหลวให้คงแอป stopped, journal NEEDS_RECOVERY และคืนเฉพาะ config ที่ transaction นี้เปลี่ยนจาก backup ที่อ่านกลับผ่านแล้ว ไม่ start เอง หากคืนไม่ได้ให้ MANUAL_RECOVERY_REQUIRED ห้ามฝืนรัน
9. เมื่อ configuration stage สำเร็จเท่านั้น รายงาน STAGED_NOT_VALIDATED ไม่เรียกว่า repair สำเร็จ การ start/recreate เป็นขั้นที่ผู้ดูแลอนุมัติภายหลังและไม่ใช่งาน GitHub นี้

## Rollback

- ใช้ transaction ID ที่ผู้ดูแลระบุเท่านั้น ตรวจ manifest, private ownership, backup integrity และ app stopped พร้อม maintenance lock ใหม่
- คืน compose จากสำเนา runtime ก่อน V3 ไม่ใช้ compose ของ main/V2 คืน hook/policies/metadata ให้ตรง baseline จริง ไม่ restore ทั้ง /data หรือ engine image อัตโนมัติ
- หากมีผู้ดูแล/Umbrel เปลี่ยน config หลัง stage ให้ BLOCKED=ROLLBACK_BASELINE_CHANGED และ review การกู้คืน ไม่ทับการแก้อื่นอย่างเงียบ ๆ ใช้ semantic/tokens/transaction journal ไม่ exact hash ของ repo
- ไฟล์ที่ก่อนหน้า absent และ V3 เพิ่ม ให้ถอดเฉพาะไฟล์ที่ journal ระบุและยังตรงกับ V3 artifact ไม่ลบ profile ที่ใช้อยู่ ตรวจ references และ saved loaded-state ก่อนคืน named policy
- rollback คงแอป stopped จนผู้ดูแลเลือก lifecycle start แล้วตรวจค่าเดิม ไม่มี automatic data rollback/downgrade
- ต้อง rehearsal rollback ใน staging รวม interrupted apply ก่อนพิจารณาใช้ production

## Validation หลังผู้ดูแลอนุมัติ start/recreate

- Docker effective security options ตรง reviewed plan และ data mounts/container_name/unknown fields ไม่เปลี่ยนจาก baseline; image/version เดิม ไม่เพิ่มสิทธิ์
- App ready เป็นเพียง availability gate ต้องทดสอบ Codex ผ่าน OpenBot tool จริงใน Workspace only รวม bwrap, อ่าน/เขียน canary ใน workspace และเขียน canary ภายนอกถูกปฏิเสธ
- outside canary ต้องเป็นไฟล์จำลองที่ underlying UID เขียนได้จริงใน baseline; ตรวจสาเหตุ denial ไม่ใช้ missing directory/permission ของไฟล์แทนหลักฐาน sandbox
- บันทึก model/account/access/Computer Use/Backup/routine states ก่อน/หลังผ่าน supported native controls โดยผู้ดูแล ไม่เปลี่ยนเพื่อให้ผ่าน
- read access ของ Shared/other-agent/credentials-like ใช้ synthetic canaries แยกจาก write test ห้ามอ่าน credentials จริง ไม่ตีความ Workspace only เป็น read isolation
- ทดสอบหลัง restart, container recreation และ package-update rehearsal ใน staging การ update อาจเขียน compose/hook ใหม่ ต้อง precheck/review ใหม่ ห้าม auto-reapply policy หรือรับประกันอยู่รอดจากเอกสารเพียงอย่างเดียว
- FUNCTIONAL_PASS และ PERSISTENCE_PASS ต้องมีหลักฐานจริงแยกกัน หากไม่ผ่านให้หยุดและ rollback ตามแผน

## Acceptance cases ที่ต้องรันก่อนเขียนว่า V3 ใช้ได้จริง

| เคส | ผลที่ต้องได้ | ผลรอบนี้ |
|---|---|---|
| เติม container_name ทั้งสามและ volume path runtime | precheck ผ่านถ้า semantics ปลอดภัย; ทุกค่าคงเดิม | NOT_RUN |
| key order/comments/quotes ต่างจาก repo | ไม่เกิด FILE_HASH_DRIFT:docker-compose.yml | NOT_RUN |
| image/mount/environment drift ที่ไม่อนุมัติ | หยุดพร้อม diff ไม่แก้อัตโนมัติ | NOT_RUN |
| security_opt ซ้ำ/หาย/ผิด type หรือ override ไม่รู้จัก | BLOCKED ไม่เลือกตัวแรก | NOT_RUN |
| YAML anchors/merge keys/aliases ที่ไม่รองรับ | BLOCKED ไม่ flatten | NOT_RUN |
| compose เปลี่ยนระหว่าง precheck กับ apply | replan ไม่มี stale patch | NOT_RUN |
| app ready/running/paused/restarting ตอน apply | ปฏิเสธก่อน backup/mutation | NOT_RUN |
| backup ไม่ครบหรือ metadata รักษาไม่ได้ | ปฏิเสธก่อน mutation | NOT_RUN |
| failed write หลังแก้ไฟล์แรก/crash กลางชุด | stopped และ recover จาก journal | NOT_RUN |
| apply ซ้ำเมื่อ configuration เหมือน plan แล้ว | no-op ยืนยัน manifest ไม่ทับ backup | NOT_RUN |
| rollback หลัง container_name เพิ่มไว้ตั้งแต่ baseline | คืน runtime baseline พร้อมชื่อเดิม | NOT_RUN |
| rollback พบ external edits หลัง stage | BLOCKED ไม่ทับ edits | NOT_RUN |
| runtime Compose/override stack และ syntax validate | ผลจริงบน host/staging | NOT_RUN |
| Codex actual-tool positive/negative canaries | ผ่านโดยไม่เพิ่มสิทธิ์ | NOT_RUN |
| read reach และ restart/update rehearsal | รายงานแยกแต่ละ gate | NOT_RUN |

## พิสูจน์แล้ว / ยังไม่พิสูจน์

พิสูจน์จากการอ่าน GitHub: V2 เดิมใช้ exact hash ของ compose และ copy template; guard retire อยู่ก่อน body; template ของ repo ไม่มี container_name ที่เจ้าของรายงานใน runtime
เจ้าของยืนยัน: production app ยัง ready, container names ทั้งสาม และผล FILE_HASH_DRIFT ดังกล่าว รอบนี้ไม่ได้อ่านหรือเปลี่ยน host เพื่อยืนยันซ้ำ

ตรวจได้รอบนี้: เนื้อหาใน branch/PR ผ่าน GitHub readback และรายการไฟล์ ไม่ได้ใช้ Local Shell, workspace file writes, host tools หรือเปลี่ยน permission

ยังไม่พิสูจน์: implementation ของ semantic YAML/hook editor, static parser/test execution, apply/rollback/crash recovery, policy safety, Codex functional tests, read isolation และ persistence ทุกเคสข้างต้นยัง NOT_RUN ไม่มี V3 deploy executable ที่ผ่านทดสอบใน PR นี้

Production ไม่ได้ถูกแก้โดยงานนี้ และยังไม่ถือว่าซ่อมสำเร็จจนกว่าจะมี implementation V3 ที่ review แล้ว ติดตั้งโดยผู้ดูแล และ Functional Test ผ่านจริง

## Read-only Compose planner prototype (ยังไม่ใช่ Installer)

เพิ่ม `tools/v3_compose_plan.py` และ `tools/test_v3_compose_plan.py` เป็น **เครื่องมือออกแบบ/ตรวจสอบเบื้องต้นเท่านั้น** ใช้ Python และ PyYAML parser node offsets เพื่อจำลองแก้ scalar เพียง 2 จุดในหน่วยความจำ โดยไม่เขียนไฟล์ ไม่เริ่ม/หยุด Docker และไม่อ่านหรือแสดง credentials

ทดสอบจากไฟล์จำลองในสภาพแวดล้อมแยกแล้ว **14/14 กรณีผ่าน** (รวม container_name ที่ Umbrel เติม, comments/quotes, source volume ที่ถูกเปลี่ยน, duplicate keys, anchors, หลาย YAML documents และ drift ที่ต้องปฏิเสธ) ไม่มีการรันกับ Compose จริงของ Mochilab

ตัวโปรแกรมใช้การตรวจแบบ fail-closed และพิมพ์เฉพาะผลตรวจ ไม่พิมพ์ environment หรือเนื้อหา Compose ทั้งไฟล์ หาก PyYAML ไม่พร้อม ให้แสดง `BLOCKED=PY_YAML_NOT_INSTALLED_NO_AUTO_INSTALL` แทนการติดตั้ง package บน Host เอง

คำสั่งทดสอบในระบบแยกที่มี PyYAML: `python3 -m unittest -v tools/test_v3_compose_plan.py`

การรันแบบอ่านอย่างเดียวบน UmbrelOS Host (หลังตรวจที่มาสคริปต์และ PyYAML): `sudo python3 tools/v3_compose_plan.py` โดยต้องเรียกจาก checkout ของ **branch V3** ไม่ใช่ branch PR #1 ตัวโปรแกรมจะไม่สร้างไฟล์ output และจะไม่เปลี่ยนค่าจริง

**ข้อจำกัด**: เช็กเฉพาะ YAML ของ Compose ฉบับเดียว ยังไม่ได้ตรวจ effective overrides, Umbrel app lifecycle, ไฟล์ Hook, AppArmor/Seccomp ใน Kernel, backup, restore หรือการทำงานจริงของ Agent จึงยัง `NOT_DEPLOYABLE`. ไม่ใช้ `RESULT=V3_COMPOSE_READ_ONLY_PLAN_PASS` เป็นเงื่อนไขให้หยุด OpenBot หรือ Apply Production
