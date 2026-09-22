export default function BrandLogo({ compact = false }: { compact?: boolean }) {
  return (
    <img
      className={compact ? "brand-logo brand-logo-compact" : "brand-logo"}
      src="/brand/chint-wordmark-green.png"
      alt="正泰 CHINT"
    />
  );
}

