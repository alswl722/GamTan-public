import Image from "next/image";
import Link from "next/link";
import { CalendarDays, FileBarChart, Gift, Sprout, UploadCloud } from "lucide-react";
import { LiveTraceFeed } from "@/components/LiveTraceFeed";

/**
 * 랜딩(/) — 두 페르소나(사장님 앱 /owner, 은행 담당자 /admin)의 입구.
 *
 * 화면 구성은 실제 제품 상태를 그대로 따라간다. 특히 측정 흐름 라벨은
 * /owner/measure의 STEPS(web/app/owner/measure/page.tsx)와 /owner 홈의
 * MEASURE_STAGES와 동일해야 한다 — 랜딩만 4장면(v0.1)으로 남아 실제 위저드
 * 5단계와 어긋나 있던 문제를 고친 것이라(2026-08-19), 단계를 늘리거나 이름을
 * 바꿀 때 세 곳을 같이 손봐야 한다.
 */

// /owner/measure STEPS와 1:1 (연동 동의·데이터 수집·결손 감지·AI 분류·리포트)
const MEASURE_STEPS = [
  {
    label: "연동 동의",
    desc: "국세청·중소벤처기업부·한국전력 마이데이터를 한 번의 동의로 병렬 수집해요.",
  },
  {
    label: "데이터 수집",
    desc: "쓰는 연료만 체크하면 필요한 서류를 알려주고, 사진·PDF·엑셀을 그대로 읽어요.",
  },
  {
    label: "결손 감지",
    desc: "빠진 달을 에이전트가 먼저 찾아 알려주고, 업종 평균으로 임시 보정해요.",
  },
  {
    label: "AI 분류",
    desc: "'지게차 경유 외 1종'을 Scope 1/2로 나누고 판단 근거를 남겨요.",
  },
  {
    label: "리포트",
    desc: "매출 추정치와 전표 실측치를 나란히 비교한 PCAF 리포트를 받아요.",
  },
] as const;

// 하단바(OwnerBottomNav)·사장님 홈의 기능 카드와 목적지를 맞춘다
const OWNER_FEATURES = [
  {
    href: "/owner/uploads",
    icon: UploadCloud,
    title: "전표 업로드",
    desc: "세금계산서·전기·도시가스 고지서를 찍어 올리면 OCR이 읽어요",
    image: "/upload_illustration.png",
    width: 480,
    height: 484,
    // 이 그림만 원본이 정사각(480×484)이고 나머지는 가로로 긴 비율이라, 높이를
    // 똑같이 맞추면 이것만 폭이 좁아 혼자 작아 보인다 — /owner 홈의 기능 카드도
    // 같은 이유로 이 그림만 한 단계 크게 준다(h-28 vs h-24).
    imgClassName: "h-[68px]",
  },
  {
    href: "/owner/report",
    icon: FileBarChart,
    title: "탄소 리포트",
    desc: "월별 추이와 동종 업종 대비 내 위치를 한 장으로",
    image: "/report_illustration.png",
    width: 548,
    height: 379,
    imgClassName: "h-14",
  },
  {
    href: "/owner/benefits",
    icon: Gift,
    title: "맞춤 혜택",
    desc: "우대금리·설비금융·정부 지원사업 후보를 골라서 안내",
    image: "/benefits_illustration.png",
    width: 601,
    height: 418,
    imgClassName: "h-14",
  },
  {
    href: "/owner/calendar",
    icon: CalendarDays,
    title: "탄소 캘린더",
    desc: "이번 달 할 일과 AI 월간 브리핑을 달력에서",
    image: "/carbon_calendar.png",
    width: 668,
    height: 428,
    imgClassName: "h-14",
  },
] as const;

const ADMIN_ITEMS = [
  { t: "포트폴리오 금융배출량", d: "PCAF Business Loans 기준 집계와 품질등급 분포" },
  { t: "담당자 검토 큐", d: "AI가 확신하지 못한 건만 사람에게 — 확정·반려 이력 기록" },
  { t: "실행·변경 이력", d: "에이전트 실행 로그와 원본문서 열람 감사 로그" },
  { t: "감사 대응·기후리스크", d: "근거 묶음 내려받기, 차주별 기후리스크 리포트" },
] as const;

export default function Home() {
  return (
    <div className="flex flex-1 flex-col items-center px-5 pb-16">
      {/* ── 히어로 ─────────────────────────────────────────────── */}
      <section className="grid w-full max-w-5xl items-center gap-9 pt-10 lg:grid-cols-[1fr_1fr] lg:gap-8 lg:pt-14">
        <div className="text-center lg:text-left">
          <h1
            className="hero-enter text-[34px] font-extrabold leading-[1.22] tracking-[-0.02em] text-ink lg:text-[42px]"
            style={{ animationDelay: "0ms" }}
          >
            전표를 읽는 AI 에이전트가
            <br />
            <span className="text-brand-ink">중소기업의 탄소</span>를
            <br />
            대신 측정합니다
          </h1>

          <p
            className="hero-enter mx-auto mt-4 max-w-md break-keep text-[14px] leading-relaxed text-muted lg:mx-0"
            style={{ animationDelay: "90ms" }}
          >
            세금계산서와 에너지 고지서만 있으면 됩니다. 에이전트가 빠진 달을 찾아내고,
            비정형 품목 텍스트를 Scope 1/2로 분류하고, 계산은 검증된 코드가 합니다.
            낮은 확신도는 사람에게 넘깁니다.
          </p>

          <div
            className="hero-enter mt-6 flex flex-col items-center gap-2.5 sm:flex-row sm:justify-center lg:justify-start"
            style={{ animationDelay: "160ms" }}
          >
            <Link
              href="/owner"
              className="btn-cta rounded-2xl bg-brand px-6 py-3.5 text-[14.5px] font-bold text-white"
            >
              사장님 앱 열기 →
            </Link>
            <Link
              href="/admin"
              className="rounded-2xl px-6 py-3.5 text-[14.5px] font-bold text-muted transition-colors hover:bg-surface hover:text-ink"
            >
              은행 담당자 대시보드 →
            </Link>
          </div>
        </div>

        <div
          className="hero-enter flex justify-center lg:justify-end"
          style={{ animationDelay: "260ms" }}
        >
          <LiveTraceFeed />
        </div>
      </section>

      {/* ── 측정 흐름 5단계 ─────────────────────────────────────
          카드 내부는 번호 배지를 제목과 같은 줄에 두는 가로 배치 —
          배지를 제목 위에 쌓으면 카드 높이가 한 줄만큼 더 늘어나 모바일에서
          5개 카드가 화면을 다 잡아먹는다(2026-08-19 사용자 피드백: "박스
          하나하나가 너무 커"). lg에서만 5열로 펼친다. */}
      <section className="mt-14 w-full max-w-5xl">
        <h2 className="text-center text-[18px] font-extrabold tracking-tight text-ink lg:text-left">
          측정은 다섯 단계로 끝납니다
        </h2>
        <ol className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          {MEASURE_STEPS.map((s, i) => (
            <li
              key={s.label}
              className="hero-enter rounded-2xl bg-surface px-3.5 py-3 shadow-card"
              style={{ animationDelay: `${320 + i * 60}ms` }}
            >
              <div className="flex items-center gap-2">
                <span className="grid h-6 w-6 shrink-0 place-items-center rounded-lg bg-brand-soft text-[11.5px] font-extrabold text-brand-ink">
                  {i + 1}
                </span>
                <span className="text-[14px] font-bold text-ink">{s.label}</span>
              </div>
              <p className="mt-1 break-keep text-[12px] leading-snug text-muted">{s.desc}</p>
            </li>
          ))}
        </ol>
      </section>

      {/* ── 사장님 앱 ─────────────────────────────────────────── */}
      <section className="mt-14 w-full max-w-5xl">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h2 className="text-[18px] font-extrabold tracking-tight text-ink">
              측정이 끝난 뒤에도 계속 씁니다
            </h2>
            <p className="mt-1 break-keep text-[13px] text-muted">
              업로드·리포트·혜택·캘린더가 사장님 앱 하단바에 그대로 들어 있어요.
            </p>
          </div>
          <Image
            src="/dandi_ddockdi.png"
            alt=""
            width={447}
            height={183}
            className="hidden h-12 w-auto shrink-0 sm:block"
          />
        </div>

        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {OWNER_FEATURES.map((f) => (
            <Link
              key={f.href}
              href={f.href}
              className="btn-cta relative flex flex-col justify-center overflow-hidden rounded-2xl bg-surface px-3.5 py-3 shadow-card transition-transform"
            >
              {/* 높이를 고정(min-h)하지 않는다 — 카드가 글 두 줄+패딩만큼만 차지하게.
                  일러스트는 absolute라 높이에 관여하지 않고 우하단 여백에 얹힌다. */}
              <span className="flex items-center gap-2">
                <span className="grid h-6 w-6 shrink-0 place-items-center rounded-lg bg-brand-soft text-brand-ink">
                  <f.icon size={14} strokeWidth={2.2} />
                </span>
                <span className="text-[13.5px] font-extrabold text-ink">{f.title}</span>
              </span>
              <span className="mt-0.5 max-w-[64%] break-keep text-[11.5px] leading-snug text-muted">
                {f.desc}
              </span>
              {/* 카드 높이가 글 기준으로 정해지므로 일러스트를 카드보다 크게 잡아도
                  레이아웃이 밀리지 않는다 — overflow-hidden이 넘치는 위쪽만 잘라낸다. */}
              <Image
                src={f.image}
                alt=""
                width={f.width}
                height={f.height}
                className={`pointer-events-none absolute -bottom-1 right-0.5 w-auto opacity-90 ${f.imgClassName}`}
              />
            </Link>
          ))}
        </div>

        <Link
          href="/owner/carbon-point"
          className="btn-cta mt-2 flex items-center gap-3 rounded-2xl bg-brand-soft px-4 py-3.5 transition-transform"
        >
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-surface text-brand-ink">
            <Sprout size={17} strokeWidth={2.2} />
          </span>
          <span className="min-w-0">
            <span className="block text-[15px] font-extrabold text-ink">
              소상공인 탄소중립포인트 신청 도우미
            </span>
            <span className="mt-0.5 block break-keep text-[12px] leading-snug text-muted">
              과거 2년 사용량과 비교해 예상 감축률을 계산하고, 신청서 초안까지 채워둡니다. 자격
              판정은 한국환경공단이 별도로 합니다.
            </span>
          </span>
        </Link>
      </section>

      {/* ── 은행 담당자 ───────────────────────────────────────── */}
      <section className="mt-14 w-full max-w-5xl">
        <div className="rounded-2xl bg-surface px-5 py-5 shadow-card sm:px-6">
          <span className="text-[11.5px] font-bold text-brand-ink">은행 ESG·여신 담당자용</span>
          <h2 className="mt-1.5 break-keep text-[18px] font-extrabold tracking-tight text-ink">
            추정치로 채워둔 중소기업 포트폴리오를 실측으로 바꿉니다
          </h2>
          <div className="mt-4 grid gap-x-6 gap-y-3 sm:grid-cols-2">
            {ADMIN_ITEMS.map((item) => (
              <div key={item.t} className="flex gap-2.5">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brand" />
                <div>
                  <div className="text-[13.5px] font-bold text-ink">{item.t}</div>
                  <p className="mt-0.5 break-keep text-[12px] leading-snug text-muted">{item.d}</p>
                </div>
              </div>
            ))}
          </div>
          <Link
            href="/admin"
            className="btn-cta mt-5 inline-block rounded-xl bg-ink px-5 py-3 text-[13.5px] font-bold text-white"
          >
            대시보드 보기 →
          </Link>
        </div>
      </section>
    </div>
  );
}
