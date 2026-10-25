import { Component, OnInit, effect, inject } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { AuthService } from './auth.service';
import { SyncStatusComponent } from './sync-status/sync-status.component';
import { SyncService } from './sync.service';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, SyncStatusComponent],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App implements OnInit {
  protected readonly auth = inject(AuthService);
  private readonly sync = inject(SyncService);

  constructor() {
    // Once signed in, show the sync status (and follow a sync already running).
    effect(() => {
      if (this.auth.isAuthenticated()) this.sync.refresh();
      else this.sync.stop();
    });
  }

  ngOnInit(): void {
    this.auth.refresh();
  }

  protected login(): void {
    this.auth.login();
  }

  protected logout(): void {
    this.auth.logout();
  }
}
