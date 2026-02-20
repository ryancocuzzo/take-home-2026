import Link from "next/link";
import { notFound } from "next/navigation";
import { getProduct } from "@/lib/api";
import { ImageGallery } from "@/components/image-gallery";
import { PriceDisplay } from "@/components/price-display";
import { Badge } from "@/components/ui/badge";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function ProductPage({ params }: PageProps) {
  const { id } = await params;

  let product;
  try {
    product = await getProduct(id);
  } catch {
    notFound();
  }

  const isOnSale =
    product.price.compare_at_price != null &&
    product.price.compare_at_price > product.price.price;

  const hexColors = product.colors.filter((c) => /^#[0-9a-fA-F]{3,6}$/.test(c));
  const namedColors = product.colors.filter((c) => !/^#[0-9a-fA-F]{3,6}$/.test(c));

  return (
    <main className="min-h-screen bg-background">
      <div className="max-w-6xl mx-auto px-4 py-8">
        <Link
          href="/"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors mb-8"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="m15 18-6-6 6-6" />
          </svg>
          Back to catalog
        </Link>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-10 lg:gap-16">
          <ImageGallery images={product.image_urls} alt={product.name} />

          <div className="flex flex-col gap-6">
            <div>
              <p className="text-sm text-muted-foreground uppercase tracking-wide mb-1">
                {product.brand}
              </p>
              <h1 className="text-2xl lg:text-3xl font-bold leading-tight">{product.name}</h1>
            </div>

            <div className="flex items-center gap-3">
              <PriceDisplay price={product.price} size="lg" />
              {isOnSale && (
                <Badge variant="destructive" className="text-xs">
                  Sale
                </Badge>
              )}
            </div>

            {product.description && (
              <div>
                <h2 className="text-sm font-semibold uppercase tracking-wide mb-2">Description</h2>
                <p className="text-sm text-muted-foreground leading-relaxed whitespace-pre-line">
                  {product.description}
                </p>
              </div>
            )}

            {product.key_features.length > 0 && (
              <div>
                <h2 className="text-sm font-semibold uppercase tracking-wide mb-2">Features</h2>
                <ul className="list-disc list-inside space-y-1">
                  {product.key_features.map((f, i) => (
                    <li key={i} className="text-sm text-muted-foreground">
                      {f}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {(hexColors.length > 0 || namedColors.length > 0) && (
              <div>
                <h2 className="text-sm font-semibold uppercase tracking-wide mb-2">Colors</h2>
                <div className="flex flex-wrap gap-2">
                  {hexColors.map((color) => (
                    <div
                      key={color}
                      className="w-7 h-7 rounded-full border border-border shadow-sm"
                      style={{ backgroundColor: color }}
                      title={color}
                    />
                  ))}
                  {namedColors.map((color) => (
                    <Badge key={color} variant="secondary" className="text-xs">
                      {color}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            <div>
              <p className="text-xs text-muted-foreground">
                Category: {product.category.name}
              </p>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
