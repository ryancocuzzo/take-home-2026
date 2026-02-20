import { getProducts } from "@/lib/api";
import { ProductCard } from "@/components/product-card";

export default async function CatalogPage() {
  const products = await getProducts();

  return (
    <main className="min-h-screen">
      <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
        <div className="mb-12 border-b border-border/60 pb-8">
          <h1 className="font-display text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            Shop
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {products.length} curated products
          </p>
        </div>
        <div className="grid grid-cols-1 gap-x-6 gap-y-10 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {products.map((product, i) => (
            <ProductCard key={product.id} product={product} priority={i === 0} />
          ))}
        </div>
      </div>
    </main>
  );
}
