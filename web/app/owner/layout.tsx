import { OwnerBottomNav } from "@/components/OwnerBottomNav";

export default function OwnerLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex w-full flex-1 flex-col">
      {/* 하단바(고정, h-14 상당)에 콘텐츠가 가려지지 않게 여백 확보 */}
      <div className="flex flex-1 flex-col pb-20">{children}</div>
      <OwnerBottomNav />
    </div>
  );
}
