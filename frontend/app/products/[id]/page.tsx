import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { getProduct } from "@/lib/api";
import { ImageGallery } from "@/components/image-gallery";
import { PriceDisplay } from "@/components/price-display";
import { Badge } from "@/components/ui/badge";

interface PageProps {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { id } = await params;
  try {
    const product = await getProduct(id);
    return {
      title: `${product.name} | Curated`,
      description: product.description?.slice(0, 160) ?? undefined,
    };
  } catch {
    return { title: "Product | Curated" };
  }
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
    <main className="min-h-screen">
      <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6 lg:px-8">
        <Link
          href="/"
          className="mb-10 inline-flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
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
          Back to shop
        </Link>

        <div className="grid grid-cols-1 gap-12 lg:grid-cols-2 lg:gap-16">
          <ImageGallery images={product.image_urls} alt={product.name} />

          <div className="flex flex-col">
            <div className="mb-6">
              <p className="mb-1 text-xs font-medium uppercase tracking-widest text-muted-foreground">
                {product.brand}
              </p>
              <h1 className="font-display text-2xl font-semibold leading-tight text-foreground lg:text-3xl">
                {product.name}
              </h1>
            </div>

            <div className="mb-8 flex items-center gap-3">
              <PriceDisplay price={product.price} size="lg" />
              {isOnSale && (
                <Badge variant="destructive" className="text-xs">
                  Sale
                </Badge>
              )}
            </div>

            {product.description && (
              <div className="mb-8">
                <h2 className="mb-3 text-xs font-semibold uppercase tracking-widest text-foreground">
                  Description
                </h2>
                <p className="text-sm leading-relaxed text-muted-foreground whitespace-pre-line">
                  {product.description}
                </p>
              </div>
            )}

            {product.key_features.length > 0 && (
              <div className="mb-8">
                <h2 className="mb-3 text-xs font-semibold uppercase tracking-widest text-foreground">
                  Details
                </h2>
                <ul className="space-y-2">
                  {product.key_features.map((f, i) => (
                    <li key={i} className="text-sm text-muted-foreground">
                      {f}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {(hexColors.length > 0 || namedColors.length > 0) && (
              <div className="mb-8">
                <h2 className="mb-3 text-xs font-semibold uppercase tracking-widest text-foreground">
                  Colors
                </h2>
                <div className="flex flex-wrap gap-2">
                  {hexColors.map((color) => (
                    <div
                      key={color}
                      className="h-8 w-8 shrink-0 rounded-full border border-border"
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

            {product.variants.length > 0 && (
              <div className="mb-8">
                <h2 className="mb-3 text-xs font-semibold uppercase tracking-widest text-foreground">
                  Available options
                </h2>
                <div className="flex flex-col gap-4">
                  {(() => {
                    const attrKeys = new Set<string>();
                    for (const v of product.variants) {
                      for (const k of Object.keys(v.attributes ?? {})) {
                        attrKeys.add(k);
                      }
                    }
                    // Color is already shown in the Colors section above
                    attrKeys.delete("color");
                    attrKeys.delete("colour");
                    if (attrKeys.size === 0) return null;
                    return Array.from(attrKeys).map((attrKey) => {
                      const values = [
                        ...new Set(
                          product.variants
                            .map((v) => (v.attributes ?? {})[attrKey])
                            .filter(Boolean)
                        ),
                      ] as string[];
                      const label =
                        attrKey.charAt(0).toUpperCase() + attrKey.slice(1);
                      return (
                        <div key={attrKey}>
                          <p className="mb-2 text-xs text-muted-foreground">
                            {label}
                          </p>
                          <div className="flex flex-wrap gap-2">
                            {values.map((val) => (
                              <Badge
                                key={val}
                                variant="outline"
                                className="text-xs font-normal"
                              >
                                {val}
                              </Badge>
                            ))}
                          </div>
                        </div>
                      );
                    });
                  })()}
                </div>
              </div>
            )}

            <div className="mt-auto border-t border-border/60 pt-6">
              <p className="text-xs text-muted-foreground">
                {product.category.name}
              </p>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
