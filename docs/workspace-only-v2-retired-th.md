# V2: ห้ามใช้ deploy production

สถานะ: RETIRED / PRODUCTION_DEPLOYMENT_PROHIBITED

อ้างอิง V2 ที่ตรวจแล้ว:
https://github.com/mochingub-kub/mochilab-openbot-store/blob/546805ef01a22267bcf9345007c5b62139b173c6/tools/apply-openbot-workspace-v2.sh

## เหตุผล

เจ้าของ production รายงาน app ยัง ready แต่ V2 precheck หยุดด้วย BLOCKED=FILE_HASH_DRIFT:docker-compose.yml ไฟล์จริงถูก Umbrel ปรับแล้ว มี container_name ทั้งสาม service ที่ไม่มีใน template ของ repo จึงไม่ควรบังคับ exact hash ให้เท่า template

body เดิมของ V2 ยังมี check_original/check_installed ที่เทียบ compose กับ OLD_COMPOSE/NEW_COMPOSE และ stage คัดลอก SOURCE/docker-compose.yml ทับ runtime วิธีนี้เสี่ยงทิ้งค่าที่ Umbrel/ผู้ดูแลเพิ่ม รวมถึง rollback เดิมที่ยอมรับ backup เฉพาะ hash template ไม่ใช่สำเนา runtime จริง

V2 ที่ commit อ้างอิงมี guard พิมพ์ BLOCKED=V2_RETIRED_UMBREL_RUNTIME_COMPOSE_REQUIRES_SEMANTIC_PATCH และ exit 2 ก่อน body แล้ว ข้อนี้ยืนยันจาก source เท่านั้น ไม่ใช่ผลรันคำสั่งในงานนี้ ห้ามนำ guard ออก ข้าม precheck หรือแก้ OLD_COMPOSE ให้เท่าไฟล์จริงเพื่อฝืนใช้ installer เดิม

## ข้อห้ามใช้งาน

- ไม่รัน V2 --stage/--verify/--rollback บน production โดยถือว่าเป็นขั้นตอนที่อนุมัติจากเอกสารนี้
- ไม่ stop แอปเพื่อแก้ FILE_HASH_DRIFT ไม่ copy repo compose ทับ runtime
- ไม่ใช้ตัว installer จาก commit เก่าก่อนมี guard
- ไม่ใช้ policy artifacts ใน deploy/workspace-only เป็นหลักฐานว่า security review และ Functional Test ผ่านแล้ว
- ไม่เปลี่ยน live files จากงาน GitHub นี้

หากเคย apply V2 จริง ต้องให้ผู้ดูแลตรวจ provenance และ backup จริงก่อนกู้คืน ห้ามใช้ V2 rollback แบบอัตโนมัติ ในเหตุการณ์ที่เจ้าของรายงาน precheck fail นั้นไม่มีหลักฐานว่า stage เริ่มแล้ว

## สิ่งที่จะมาแทน

อ่าน [แนวทาง V3 แบบ semantic patch](workspace-only-v3-th.md) ใช้ runtime baseline, backup จริง, allowed-key edits, apply/rollback ตอน stopped และ functional validation

V3 ตอนนี้เป็น DESIGN_ONLY ยังไม่ใช่คำสั่ง deploy ที่ใช้ได้จริง Draft PR ใหม่นี้ไม่แก้ PR #1 และไม่ merge/update แอป
