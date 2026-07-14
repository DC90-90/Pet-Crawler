import { Suspense } from "react";
import { Outlet, useNavigation as useRouterNavigation } from "react-router-dom";
import { Spinner } from "@heroui/react";
import { Header } from "@/components/site/Header";
import { Footer } from "@/components/site/Footer";
import { AnnouncementBar } from "@/components/site/AnnouncementBar";
import { WhatsAppFab } from "@/components/site/WhatsAppFab";
import { PopupHost } from "@/components/site/PopupHost";
import { useContentVersionSync } from "@/lib/queries";

function RouteFallback() {
  return (
    <div className="grid min-h-[50vh] place-items-center">
      <Spinner />
    </div>
  );
}

export function PublicLayout() {
  useContentVersionSync();
  const routerNav = useRouterNavigation();

  return (
    <div className="flex min-h-dvh flex-col">
      <AnnouncementBar />
      <Header />
      <main id="main" className="flex-1">
        {routerNav.state === "loading" ? (
          <RouteFallback />
        ) : (
          <Suspense fallback={<RouteFallback />}>
            <Outlet />
          </Suspense>
        )}
      </main>
      <Footer />
      <WhatsAppFab />
      <PopupHost />
    </div>
  );
}
