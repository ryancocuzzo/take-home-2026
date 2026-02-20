import type { Price } from "@/types/product";

interface PriceDisplayProps {
  price: Price;
  size?: "sm" | "lg";
}

function formatPrice(amount: number, currency: string): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format(amount);
}

export function PriceDisplay({ price, size = "sm" }: PriceDisplayProps) {
  const isOnSale = price.compare_at_price != null && price.compare_at_price > price.price;
  const mainSize = size === "lg" ? "text-2xl font-bold" : "text-base font-semibold";
  const strikeSize = size === "lg" ? "text-base" : "text-sm";

  return (
    <div className="flex items-baseline gap-2">
      <span className={`${mainSize} ${isOnSale ? "text-destructive" : "text-foreground"}`}>
        {formatPrice(price.price, price.currency)}
      </span>
      {isOnSale && (
        <span className={`${strikeSize} text-muted-foreground line-through`}>
          {formatPrice(price.compare_at_price!, price.currency)}
        </span>
      )}
    </div>
  );
}
