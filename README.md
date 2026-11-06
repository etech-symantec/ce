# Cisco CE Watch

Cisco Learning Network의 Rev Up to Recert 관련 글을 매일 검색해 최근 6개월 후보 링크를 보여주는 GitHub Pages 대시보드입니다.

## 설치 / 배포

1. GitHub에서 **새 저장소**를 만듭니다. 이 폴더 안의 **모든 파일과 숨김 폴더 `.github`까지** 저장소 루트에 업로드합니다.
2. 저장소 **Settings → Actions → General → Workflow permissions**에서 **Read and write permissions**를 허용합니다. 조직 정책이 막으면 관리자 확인이 필요합니다.
3. **Actions → Update Cisco CE Watch → Run workflow**로 첫 수집을 실행합니다.
4. **Settings → Pages → Build and deployment → Source: Deploy from a branch → Branch: main, /(root)** 로 설정합니다.
5. 공개 저장소의 경우 대시보드는 `https://<계정>.github.io/<저장소명>/`에서 표시됩니다. 비공개 저장소 Pages 이용 가능 여부는 요금제/조직 정책을 확인하세요.

## 자동화

- 매일 **한국 시간 오전 9시**에 GitHub Actions 실행 (`UTC 00:00`, 일정은 GitHub 사정에 따라 지연 가능)
- **Action 수동 실행**도 지원
- 최근 183일간 **Cisco Blogs 공식 RSS(Cisco U./Cisco Certifications/Cisco Learning Network)를 직접 수집**하고, 본문에서 Rev Up/CE 관련성을 확인해 후보로 저장\n- Google News RSS는 Cisco Learning Network의 동적 게시판을 보완하는 **보조 발견 경로**로만 사용
- Cisco Learning Network 게시판은 Salesforce 기반 동적 로딩이라 전체 목록 직접 수집을 보장하지 않음. 대신 Cisco 공식 블로그 RSS를 1차 소스로 사용하고 게시판 접근 상태는 status.json에 기록
- `data/posts.json`에 발견한 글 저장, `data/status.json`에 수집 상태와 실패 원인 기록
- `data/courses.json`에는 **사람이 확인한 CE 과정**만 저장. 새 후보를 자동으로 '무료 확정' 또는 'CE 확정'으로 승격하지 않음
- Github Actions가 커밋하면 GitHub Pages에 변경 내용 반영

## 수집 문제 확인

Actions 실행 로그와 `data/status.json`의 `topic_access`, `rss_queries_succeeded`, `errors`를 확인하세요. 우선 `official_feeds_succeeded`가 1 이상인지 확인하세요. 공식 RSS가 실패하면 Google News 보조 검색을 사용하지만, Google News 결과에는 원문 주소가 누락될 수 있습니다. 사이트를 무단 우회하거나 로그인 정보를 수집하지 않습니다.

로컬 테스트: `pip install -r requirements.txt && python scripts/update_ce.py && python -m http.server 8000`, 접속 `http://localhost:8000`.
