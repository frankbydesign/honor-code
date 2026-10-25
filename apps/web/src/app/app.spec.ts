import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { App } from './app';

describe('App', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
  });

  it('should create the app', () => {
    const fixture = TestBed.createComponent(App);
    const app = fixture.componentInstance;
    expect(app).toBeTruthy();
  });

  it('should render title', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('h1')?.textContent).toContain('Honor Code');
  });
});

describe('App (signed in)', () => {
  it('renders the nav, the sync status line, and a router outlet', async () => {
    const { HttpTestingController } = await import('@angular/common/http/testing');
    const { provideRouter } = await import('@angular/router');
    TestBed.resetTestingModule();
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();
    const http = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    http.expectOne('/api/auth/me').flush({ email: 'frank@example.com', display_name: 'Frank' });
    fixture.detectChanges();
    http.match('/api/sync').forEach((r) =>
      r.flush({ configured: false, missing: ['FATHOM_API_KEY'], running: false, last_run: null }),
    );
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;

    const links = Array.from(el.querySelectorAll('nav a')).map((a) => a.textContent!.trim());
    expect(links).toEqual(['Review', 'Meetings']);
    expect(el.querySelector('router-outlet')).not.toBeNull();
    expect(el.querySelector('[data-testid="sync-status"]')?.textContent).toContain('FATHOM_API_KEY');
  });
});
