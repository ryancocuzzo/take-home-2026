import Link from "next/link";
import Image from "next/image";
import type { ProductSummary } from "@/types/product";
import { PriceDisplay } from "@/components/price-display";

interface ProductCardProps {
  product: ProductSummary;
  priority?: boolean;
}

export function ProductCard({ product, priority = false }: ProductCardProps) {
  return (
    <Link
      href={`/products/${product.id}`}
      className="group flex flex-col rounded-xl border bg-card overflow-hidden shadow-sm hover:shadow-md transition-shadow duration-200"
    >
      <div className="relative aspect-square bg-muted overflow-hidden">
        {product.image_url ? (
          <Image
            src={product.image_url}
            alt={product.name}
            fill
            sizes="(max-width: 640px) 100vw, (max-width: 1024px) 50vw, 25vw"
            className="object-cover group-hover:scale-105 transition-transform duration-300"
            priority={priority}
          />
        ) : (
          <div className="flex h-full items-center justify-center text-muted-foreground text-sm">
            No image
          </div>
        )}
      </div>
      <div className="flex flex-col gap-1 p-4">
        <p className="text-xs text-muted-foreground uppercase tracking-wide">{product.brand}</p>
        <h2 className="text-sm font-medium leading-snug line-clamp-2 group-hover:text-primary transition-colors">
          {product.name}
        </h2>
        <div className="mt-1">
          <PriceDisplay price={product.price} />
        </div>
      </div>
    </Link>
  );
}
