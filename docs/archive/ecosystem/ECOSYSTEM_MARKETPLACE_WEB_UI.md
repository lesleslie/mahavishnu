# Ecosystem Marketplace - Web UI Specification

## Overview

The Ecosystem Marketplace web UI provides a user-friendly interface for browsing, discovering, installing, and managing Mahavishnu packages. Built with React and FastAPI, it offers real-time search, secure payment processing, and comprehensive package management.

## Architecture

### Frontend Stack

- **Framework**: React 18+ with TypeScript
- **State Management**: Zustand
- **Routing**: React Router v6
- **UI Components**: shadcn/ui (Radix UI + Tailwind CSS)
- **Forms**: React Hook Form + Zod validation
- **Data Fetching**: TanStack Query (React Query)
- **Authentication**: JWT tokens + context
- **Payment**: Stripe Elements
- **Real-time**: WebSocket notifications

### Backend Stack

- **Framework**: FastAPI (Python)
- **Database**: PostgreSQL + pgvector
- **Caching**: Redis
- **Search**: Elasticsearch
- **File Storage**: AWS S3 / Cloudflare R2
- **Payment**: Stripe
- **Authentication**: JWT + OAuth2 (GitHub, Google)
- **Real-time**: WebSocket (FastAPI WebSocket)

## Pages

### 1. Home Page (`/`)

**Features:**
- Hero section with search bar
- Trending packages carousel
- Categories grid
- Recent activity feed
- Statistics overview

**Components:**
```tsx
<HomePage>
  <Hero />
  <TrendingCarousel />
  <CategoriesGrid />
  <RecentActivity />
  <MarketplaceStats />
</HomePage>
```

**Example:**
```tsx
// src/pages/HomePage.tsx
export function HomePage() {
  const { data: trending, isLoading } = useQuery({
    queryKey: ['trending'],
    queryFn: api.getTrending,
  });

  return (
    <div className="container mx-auto px-4 py-8">
      <Hero />
      <TrendingCarousel packages={trending} />
      <CategoriesGrid />
      <RecentActivity />
    </div>
  );
}
```

### 2. Package Browser (`/packages`)

**Features:**
- Search bar with filters
- Category sidebar
- Sort options (relevance, downloads, rating, updated)
- Package grid/list view toggle
- Pagination
- Advanced filters (license, price, verification)

**URL Parameters:**
```
/packages?q=search&category=agent&verified=true&sort=downloads&page=1
```

**Components:**
```tsx
<PackageBrowser>
  <SearchBar />
  <FiltersSidebar>
    <CategoryFilter />
    <LicenseFilter />
    <PriceFilter />
    <VerificationFilter />
  </FiltersSidebar>
  <SortDropdown />
  <ViewToggle />
  <PackageGrid />
  <Pagination />
</PackageBrowser>
```

**Example:**
```tsx
// src/pages/PackageBrowser.tsx
export function PackageBrowser() {
  const [searchParams] = useSearchParams();
  const { data: packages } = useQuery({
    queryKey: ['packages', searchParams.toString()],
    queryFn: () => api.searchPackages(Object.fromEntries(searchParams)),
  });

  return (
    <div className="flex">
      <FiltersSidebar />
      <div className="flex-1">
        <SearchBar />
        <PackageGrid packages={packages?.items} />
        <Pagination total={packages?.total} />
      </div>
    </div>
  );
}
```

### 3. Package Detail Page (`/packages/:id`)

**Features:**
- Package header (name, icon, verification badge)
- Description and long description
- Screenshots gallery
- Installation instructions (with code snippets)
- Version history
- Dependencies list
- Statistics (downloads, rating, reviews)
- Reviews section with pagination
- Related packages
- Install/Update buttons
- Shopping cart (for paid packages)

**Components:**
```tsx
<PackageDetail>
  <PackageHeader />
  <PackageStats />
  <ScreenshotsGallery />
  <InstallationGuide />
  <DependenciesList />
  <VersionHistory />
  <ReviewsSection />
  <RelatedPackages />
  <InstallButton />
  <AddToCartButton />
</PackageDetail>
```

**Example:**
```tsx
// src/pages/PackageDetail.tsx
export function PackageDetail() {
  const { id } = useParams();
  const { data: pkg } = useQuery({
    queryKey: ['package', id],
    queryFn: () => api.getPackage(id),
  });

  const { data: reviews } = useQuery({
    queryKey: ['reviews', id],
    queryFn: () => api.getReviews(id),
  });

  const installMutation = useMutation({
    mutationFn: api.installPackage,
    onSuccess: () => toast.success('Package installed!'),
  });

  return (
    <div className="container mx-auto px-4 py-8">
      <PackageHeader package={pkg} />
      <PackageStats package={pkg} />
      <Button onClick={() => installMutation.mutate(pkg.id)}>
        Install Package
      </Button>
      <ReviewsSection reviews={reviews} />
    </div>
  );
}
```

### 4. User Profile (`/profile`)

**Features:**
- Profile header (avatar, display name, bio)
- Statistics (packages, downloads, earnings)
- Published packages tab
- Installed packages tab
- Reviews tab
- Earnings dashboard (with charts)
- Settings form (email, password, etc.)

**Components:**
```tsx
<UserProfile>
  <ProfileHeader />
  <ProfileTabs>
    <PublishedPackages />
    <InstalledPackages />
    <Reviews />
    <EarningsDashboard />
  </ProfileTabs>
  <SettingsForm />
</UserProfile>
```

**Example:**
```tsx
// src/pages/UserProfile.tsx
export function UserProfile() {
  const { data: profile } = useQuery({
    queryKey: ['profile'],
    queryFn: api.getProfile,
  });

  const [activeTab, setActiveTab] = useState('published');

  return (
    <div className="container mx-auto px-4 py-8">
      <ProfileHeader profile={profile} />
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="published">Published</TabsTrigger>
          <TabsTrigger value="installed">Installed</TabsTrigger>
          <TabsTrigger value="reviews">Reviews</TabsTrigger>
          <TabsTrigger value="earnings">Earnings</TabsTrigger>
        </TabsList>
        <TabsContent value="published">
          <PublishedPackages packages={profile?.published_packages} />
        </TabsContent>
        <TabsContent value="installed">
          <InstalledPackages packages={profile?.installed_packages} />
        </TabsContent>
        <TabsContent value="reviews">
          <UserReviews reviews={profile?.reviews} />
        </TabsContent>
        <TabsContent value="earnings">
          <EarningsDashboard earnings={profile?.earnings} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
```

### 5. Shopping Cart (`/cart`)

**Features:**
- Cart items list (with quantity)
- Package details preview
- Remove items
- Price calculation (one-time vs subscription)
- Promo code input
- Checkout button

**Components:**
```tsx
<ShoppingCart>
  <CartItems />
  <OrderSummary />
  <PromoCodeInput />
  <CheckoutButton />
</ShoppingCart>
```

**Example:**
```tsx
// src/pages/ShoppingCart.tsx
export function ShoppingCart() {
  const { data: cart } = useQuery({
    queryKey: ['cart'],
    queryFn: api.getCart,
  });

  const removeMutation = useMutation({
    mutationFn: api.removeFromCart,
    onSuccess: () => queryClient.invalidateQueries(['cart']),
  });

  return (
    <div className="container mx-auto px-4 py-8">
      <h1>Shopping Cart</h1>
      <CartItems
        items={cart?.items}
        onRemove={(id) => removeMutation.mutate(id)}
      />
      <OrderSummary cart={cart} />
      <Button onClick={() => navigate('/checkout')}>
        Proceed to Checkout
      </Button>
    </div>
  );
}
```

### 6. Checkout Page (`/checkout`)

**Features:**
- Order summary
- Stripe Elements (card details)
- Payment method selector (card, PayPal)
- Billing address form
- Tax calculation
- Terms and conditions
- Place order button

**Components:**
```tsx
<CheckoutPage>
  <OrderSummary />
  <StripeElements>
    <CardElement />
  </StripeElements>
  <BillingAddressForm />
  <TaxDisplay />
  <PlaceOrderButton />
</CheckoutPage>
```

**Example:**
```tsx
// src/pages/CheckoutPage.tsx
export function CheckoutPage() {
  const { data: cart } = useQuery({
    queryKey: ['cart'],
    queryFn: api.getCart,
  });

  const checkoutMutation = useMutation({
    mutationFn: api.createCheckoutSession,
    onSuccess: (data) => {
      window.location.href = data.stripe_checkout_url;
    },
  });

  return (
    <div className="container mx-auto px-4 py-8">
      <h1>Checkout</h1>
      <OrderSummary cart={cart} />
      <Elements stripe={stripePromise}>
        <CheckoutForm
          onSubmit={(data) => checkoutMutation.mutate(data)}
        />
      </Elements>
    </div>
  );
}
```

### 7. Publish Package (`/publish`)

**Features:**
- Package metadata form (name, description, category, etc.)
- Upload package file (drag & drop)
- Upload screenshots
- Set pricing (free, one-time, subscription)
- License selector
- Dependency manager
- Preview card
- Submit for review button

**Components:**
```tsx
<PublishPage>
  <PackageForm>
    <NameInput />
    <DescriptionInput />
    <CategorySelect />
    <LicenseSelect />
    <PackageUpload />
    <ScreenshotsUpload />
    <PricingOptions />
    <DependenciesEditor />
  </PackageForm>
  <PreviewCard />
  <SubmitButton />
</PublishPage>
```

**Example:**
```tsx
// src/pages/PublishPage.tsx
export function PublishPage() {
  const form = useForm({
    schema: publishPackageSchema,
    defaultValues: {
      name: '',
      description: '',
      category: '',
      license: 'MIT',
      price_usd: 0,
    },
  });

  const publishMutation = useMutation({
    mutationFn: api.publishPackage,
    onSuccess: () => toast.success('Package submitted for review!'),
  });

  return (
    <div className="container mx-auto px-4 py-8">
      <h1>Publish Package</h1>
      <Form {...form}>
        <form onSubmit={form.handleSubmit((data) => publishMutation.mutate(data))}>
          <FormField name="name" render={({ field }) => (
            <FormItem>
              <FormLabel>Package Name</FormLabel>
              <FormControl>
                <Input {...field} />
              </FormControl>
            </FormItem>
          )}
          />
          {/* More fields... */}
          <Button type="submit">Submit for Review</Button>
        </form>
      </Form>
    </div>
  );
}
```

### 8. Admin Dashboard (`/admin`)

**Features:**
- Overview statistics (packages, users, revenue)
- Pending review queue
- User management
- Package management
- Moderation tools
- Reports and analytics
- System health monitoring

**Components:**
```tsx
<AdminDashboard>
  <OverviewStats />
  <PendingReviewQueue />
  <UserManagement />
  <PackageManagement />
  <ModerationTools />
  <Analytics />
  <SystemHealth />
</AdminDashboard>
```

## Components

### PackageCard

Display package in grid/list view.

```tsx
interface PackageCardProps {
  package: Package;
  view: 'grid' | 'list';
}

export function PackageCard({ package: pkg, view }: PackageCardProps) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-4">
          <PackageIcon src={pkg.icon_url} />
          <div>
            <CardTitle>{pkg.name}</CardTitle>
            <CardDescription>{pkg.description}</CardDescription>
          </div>
          {pkg.verified && <VerifiedBadge />}
        </div>
      </CardHeader>
      <CardContent>
        <PackageStats package={pkg} />
        <PackageTags tags={pkg.tags} />
      </CardContent>
      <CardFooter>
        <Button onClick={() => navigate(`/packages/${pkg.id}`)}>
          View Details
        </Button>
      </CardFooter>
    </Card>
  );
}
```

### SearchBar

Global search with autocomplete.

```tsx
export function SearchBar() {
  const [query, setQuery] = useState('');
  const navigate = useNavigate();

  const { data: suggestions } = useQuery({
    queryKey: ['search-suggestions', query],
    queryFn: () => api.getSearchSuggestions(query),
    enabled: query.length > 2,
  });

  return (
    <div className="relative">
      <Input
        type="search"
        placeholder="Search packages..."
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && navigate(`/packages?q=${query}`)}
      />
      {suggestions && (
        <SearchSuggestions
          suggestions={suggestions}
          onSelect={(s) => navigate(`/packages/${s.id}`)}
        />
      )}
    </div>
  );
}
```

### InstallButton

Install package with status indicator.

```tsx
interface InstallButtonProps {
  packageId: string;
  version?: string;
}

export function InstallButton({ packageId, version }: InstallButtonProps) {
  const { data: installed } = useQuery({
    queryKey: ['installed', packageId],
    queryFn: () => api.getInstalledPackage(packageId),
  });

  const installMutation = useMutation({
    mutationFn: () => api.installPackage(packageId, version),
    onSuccess: () => {
      toast.success('Package installed!');
      queryClient.invalidateQueries(['installed', packageId]);
    },
  });

  if (installed) {
    return (
      <Button variant="outline" disabled>
        Installed
      </Button>
    );
  }

  return (
    <Button onClick={() => installMutation.mutate()}>
      Install
    </Button>
  );
}
```

### RatingStars

Display and submit ratings.

```tsx
interface RatingStarsProps {
  rating: number;
  readonly?: boolean;
  onRate?: (rating: number) => void;
}

export function RatingStars({ rating, readonly, onRate }: RatingStarsProps) {
  const [hover, setHover] = useState(0);

  return (
    <div className="flex gap-1">
      {[1, 2, 3, 4, 5].map((star) => (
        <Star
          key={star}
          filled={star <= (hover || rating)}
          readonly={readonly}
          onMouseEnter={() => !readonly && setHover(star)}
          onMouseLeave={() => !readonly && setHover(0)}
          onClick={() => !readonly && onRate?.(star)}
        />
      ))}
    </div>
  );
}
```

### ReviewForm

Submit package review.

```tsx
export function ReviewForm({ packageId }: { packageId: string }) {
  const form = useForm({
    schema: reviewSchema,
    defaultValues: {
      rating: 5,
      title: '',
      content: '',
    },
  });

  const reviewMutation = useMutation({
    mutationFn: (data: ReviewInput) => api.submitReview(packageId, data),
    onSuccess: () => {
      toast.success('Review submitted!');
      queryClient.invalidateQueries(['reviews', packageId]);
    },
  });

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit((data) => reviewMutation.mutate(data))}>
        <FormField name="rating" render={() => (
          <FormItem>
            <FormLabel>Rating</FormLabel>
            <FormControl>
              <RatingStars
                rating={form.watch('rating')}
                onRate={(r) => form.setValue('rating', r)}
              />
            </FormControl>
          </FormItem>
        )} />
        <FormField name="title" render={({ field }) => (
          <FormItem>
            <FormLabel>Title</FormLabel>
            <FormControl>
              <Input {...field} />
            </FormControl>
          </FormItem>
        )} />
        <FormField name="content" render={({ field }) => (
          <FormItem>
            <FormLabel>Review</FormLabel>
            <FormControl>
              <Textarea {...field} />
            </FormControl>
          </FormItem>
        )} />
        <Button type="submit">Submit Review</Button>
      </form>
    </Form>
  );
}
```

## State Management

### Global Store (Zustand)

```typescript
// src/store/marketplaceStore.ts
interface MarketplaceStore {
  cart: CartItem[];
  user: User | null;
  search: {
    query: string;
    filters: Filters;
    sort: SortOption;
  };

  addToCart: (item: CartItem) => void;
  removeFromCart: (itemId: string) => void;
  setUser: (user: User | null) => void;
  setSearch: (search: Partial<MarketplaceStore['search']>) => void;
}

export const useMarketplaceStore = create<MarketplaceStore>((set) => ({
  cart: [],
  user: null,
  search: {
    query: '',
    filters: {},
    sort: 'relevance',
  },

  addToCart: (item) => set((state) => ({
    cart: [...state.cart, item],
  })),

  removeFromCart: (itemId) => set((state) => ({
    cart: state.cart.filter((item) => item.id !== itemId),
  })),

  setUser: (user) => set({ user }),

  setSearch: (search) => set((state) => ({
    search: { ...state.search, ...search },
  })),
}));
```

## API Integration

### React Query Setup

```typescript
// src/lib/api.ts
import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 5 * 60 * 1000, // 5 minutes
    },
  },
});

export const api = {
  // Packages
  searchPackages: (params: SearchParams) =>
    fetch('/api/v1/packages?' + new URLSearchParams(params)).then((r) => r.json()),

  getPackage: (id: string) =>
    fetch(`/api/v1/packages/${id}`).then((r) => r.json()),

  installPackage: (id: string, version?: string) =>
    fetch(`/api/v1/packages/install`, {
      method: 'POST',
      body: JSON.stringify({ package_id: id, version }),
    }).then((r) => r.json()),

  // Reviews
  getReviews: (packageId: string) =>
    fetch(`/api/v1/packages/${packageId}/reviews`).then((r) => r.json()),

  submitReview: (packageId: string, data: ReviewInput) =>
    fetch(`/api/v1/packages/${packageId}/reviews`, {
      method: 'POST',
      body: JSON.stringify(data),
    }).then((r) => r.json()),

  // User
  getProfile: () =>
    fetch('/api/v1/users/me').then((r) => r.json()),

  // Cart
  getCart: () =>
    fetch('/api/v1/cart').then((r) => r.json()),

  addToCart: (packageId: string) =>
    fetch('/api/v1/cart', {
      method: 'POST',
      body: JSON.stringify({ package_id: packageId }),
    }).then((r) => r.json()),
};
```

## Authentication

### Auth Provider

```tsx
// src/providers/AuthProvider.tsx
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    // Check for existing session
    api.getProfile().then(setUser).catch(() => setUser(null));
  }, []);

  const login = async (provider: 'github' | 'google') => {
    window.location.href = `/api/v1/auth/${provider}`;
  };

  const logout = async () => {
    await fetch('/api/v1/auth/logout', { method: 'POST' });
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
```

## Payment Integration

### Stripe Checkout

```tsx
// src/components/CheckoutForm.tsx
import { loadStripe } from '@stripe/stripe-js';
import { Elements, CardElement, useStripe, useElements } from '@stripe/react-stripe-js';

const stripePromise = loadStripe('pk_test_...');

function CheckoutForm() {
  const stripe = useStripe();
  const elements = useElements();

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();

    const { error, paymentMethod } = await stripe.createPaymentMethod({
      type: 'card',
      card: elements.getElement(CardElement)!,
    });

    if (error) {
      toast.error(error.message);
    } else {
      // Send paymentMethod.id to backend
      await api.confirmPayment({ payment_method_id: paymentMethod.id });
      toast.success('Payment successful!');
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <CardElement />
      <Button type="submit" disabled={!stripe}>
        Pay
      </Button>
    </form>
  );
}

export function CheckoutPage() {
  return (
    <Elements stripe={stripePromise}>
      <CheckoutForm />
    </Elements>
  );
}
```

## Responsive Design

### Mobile-First Breakpoints

```css
/* tailwind.config.js */
module.exports = {
  theme: {
    screens: {
      'sm': '640px',
      'md': '768px',
      'lg': '1024px',
      'xl': '1280px',
      '2xl': '1536px',
    },
  },
};
```

### Responsive Package Grid

```tsx
export function PackageGrid({ packages }: { packages: Package[] }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      {packages.map((pkg) => (
        <PackageCard key={pkg.id} package={pkg} />
      ))}
    </div>
  );
}
```

## Accessibility

### WCAG 2.1 AA Compliance

- Semantic HTML elements
- ARIA labels for interactive elements
- Keyboard navigation support
- Focus indicators
- Screen reader support
- Color contrast ratios
- Alt text for images

### Example: Accessible Button

```tsx
export function AccessibleButton({ children, ...props }: ButtonProps) {
  return (
    <button
      {...props}
      role="button"
      aria-label={props['aria-label'] || typeof children === 'string' ? children : 'Button'}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          props.onClick?.(e as any);
        }
      }}
    >
      {children}
    </button>
  );
}
```

## Testing

### Unit Tests (Vitest)

```typescript
// src/components/__tests__/PackageCard.test.tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PackageCard } from '../PackageCard';

describe('PackageCard', () => {
  it('renders package name and description', () => {
    const package = {
      id: 'test-001',
      name: 'Test Package',
      description: 'Test description',
      // ... other fields
    };

    render(<PackageCard package={package} view="grid" />);

    expect(screen.getByText('Test Package')).toBeInTheDocument();
    expect(screen.getByText('Test description')).toBeInTheDocument();
  });

  it('shows verified badge when package is verified', () => {
    const package = {
      id: 'test-001',
      name: 'Test Package',
      verified: true,
    };

    render(<PackageCard package={package} view="grid" />);

    expect(screen.getByLabelText('Verified')).toBeInTheDocument();
  });
});
```

### E2E Tests (Playwright)

```typescript
// tests/e2e/package-install.spec.ts
import { test, expect } from '@playwright/test';

test('install package from marketplace', async ({ page }) => {
  await page.goto('/packages/test-package-001');

  await page.click('button:has-text("Install")');

  await expect(page.locator('.toast-success')).toHaveText('Package installed!');
});

test('search for packages', async ({ page }) => {
  await page.goto('/packages');

  await page.fill('input[placeholder="Search packages..."]', 'data pipeline');
  await page.press('input[placeholder="Search packages..."]', 'Enter');

  await expect(page.locator('.package-card')).toHaveCount(10);
});
```

## Deployment

### Build Commands

```bash
# Build for production
npm run build

# Preview production build
npm run preview

# Run tests
npm run test

# Run linter
npm run lint

# Type check
npm run type-check
```

### Dockerfile

```dockerfile
# Frontend Dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

### Docker Compose

```yaml
version: '3.8'

services:
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "3000:80"
    environment:
      - VITE_API_URL=http://backend:8000

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/marketplace
      - REDIS_URL=redis://redis:6379

  db:
    image: postgres:16
    environment:
      - POSTGRES_DB=marketplace
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data

volumes:
  postgres_data:
  redis_data:
```

## Performance Optimization

### Code Splitting

```tsx
// Lazy load pages
const PackageDetail = lazy(() => import('./pages/PackageDetail'));
const UserProfile = lazy(() => import('./pages/UserProfile'));

function App() {
  return (
    <Suspense fallback={<LoadingSpinner />}>
      <Routes>
        <Route path="/packages/:id" element={<PackageDetail />} />
        <Route path="/profile" element={<UserProfile />} />
      </Routes>
    </Suspense>
  );
}
```

### Image Optimization

```tsx
import Image from 'next/image';

export function PackageIcon({ src, alt }: { src: string; alt: string }) {
  return (
    <Image
      src={src}
      alt={alt}
      width={64}
      height={64}
      loading="lazy"
    />
  );
}
```

### Bundle Analysis

```bash
npm run build -- --analyze
```

## Monitoring

### Error Tracking (Sentry)

```typescript
import * as Sentry from '@sentry/react';

Sentry.init({
  dsn: 'YOUR_SENTRY_DSN',
  integrations: [new Sentry.BrowserTracing()],
  tracesSampleRate: 1.0,
});
```

### Analytics

```typescript
// Track page views
import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

export function useAnalytics() {
  const location = useLocation();

  useEffect(() => {
    window.gtag('event', 'page_view', {
      page_path: location.pathname,
    });
  }, [location]);
}
```

## Conclusion

This specification provides a comprehensive blueprint for building the Ecosystem Marketplace web UI. The architecture is designed for scalability, performance, and user experience, with best practices for testing, deployment, and monitoring.

Key features:
- Modern React 18+ with TypeScript
- Comprehensive component library
- Real-time search and updates
- Secure payment processing
- Responsive mobile-first design
- WCAG 2.1 AA accessibility
- Full test coverage
- Production-ready deployment
